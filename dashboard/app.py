"""BOAZ Signal 펀드·ETF 설명 리스크 대시보드 (3화면 프로토타입).

로컬 실행:
    DASHBOARD_DATA_ROOT=../signal-data/exports/dashboard \
    uv run --with-requirements dashboard/requirements.txt \
        streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

_DASHBOARD_DIR = Path(__file__).resolve().parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from constants import (
    AXIS4_ITEM_MAP,
    AXIS4_ITEM_ORDER,
    DISCLAIMER_TEXT,
    REWRITE_DISCLAIMER_TEXT,
    STATUS_COLORS,
    STATUS_ORDER,
)
from data_loader import DashboardBundle, load_bundle, resolve_data_root

DEFAULT_LOCAL_ROOT = (
    _DASHBOARD_DIR.parent.parent / "signal-data" / "exports" / "dashboard"
)

PAGE_OPTIONS = [
    "화면 1 · 전체 분포 및 잔차 상위 목록",
    "화면 2 · 상품 상세 드릴다운",
    "화면 3 · 감점 분해 · 쉬운 문장 · 제재 검증",
]


@st.cache_data(ttl=300, show_spinner="공식 내보내기 파일을 불러오는 중...")
def _cached_bundle(data_root: str) -> DashboardBundle:
    return load_bundle(data_root)


def _format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def _format_num(value: float | None, digits: int = 4) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.{digits}f}"


def _render_banner(bundle: DashboardBundle) -> None:
    official = bundle.official
    summary = bundle.residual_summary
    st.warning(DISCLAIMER_TEXT)
    c1, c2, c3, c4 = st.columns(4)
    c1.caption(f"공식 실행: `{official.get('score_run_id', '-')}`")
    c2.caption(f"기준일(최신 접수일): **{official.get('baseline_date', '-')}**")
    c3.caption(
        f"회귀 분석 펀드 묶음: **{summary.get('used', 0)} / {summary.get('groups', 0)}개**"
    )
    c4.caption("기본 잔차 모형: **모형 B (위험등급 + ETF + 운용사 고정효과)**")


def _apply_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, str, bool]:
    st.sidebar.header("공통 필터")

    product_type = st.sidebar.radio(
        "상품군",
        options=["전체", "공모펀드", "ETF"],
        horizontal=True,
    )
    grades = sorted(g for g in df["risk_grade"].dropna().astype(int).unique().tolist())
    selected_grades = st.sidebar.multiselect(
        "위험등급 (1=매우 높은 위험 ~ 6=매우 낮은 위험, 비우면 전체)",
        options=grades,
        default=grades,
    )
    managers = sorted(df["manager"].dropna().unique().tolist())
    selected_managers = st.sidebar.multiselect(
        "운용사 (비우면 전체)",
        options=managers,
        default=[],
    )
    model_choice = st.sidebar.radio(
        "잔차 기준 모형",
        options=["model_b", "model_a"],
        format_func=lambda m: (
            "모형 B: 위험등급+ETF+운용사 고정효과 (기본)"
            if m == "model_b"
            else "모형 A: 위험등급+ETF"
        ),
    )
    include_excluded = st.sidebar.checkbox(
        "회귀 제외 묶음 포함 (외국 엄브렐러·동률 등)",
        value=False,
    )

    filtered = df.copy()
    if product_type == "공모펀드":
        filtered = filtered[~filtered["is_etf"]]
    elif product_type == "ETF":
        filtered = filtered[filtered["is_etf"]]

    if selected_grades:
        if include_excluded:
            filtered = filtered[
                filtered["risk_grade"].isin(selected_grades)
                | filtered["risk_grade"].isna()
            ]
        else:
            filtered = filtered[filtered["risk_grade"].isin(selected_grades)]

    if selected_managers:
        filtered = filtered[filtered["manager"].isin(selected_managers)]

    if not include_excluded:
        filtered = filtered[filtered["exclude_reason"].isna()]

    return filtered, model_choice, include_excluded


def _render_screen_1(
    bundle: DashboardBundle,
    filtered: pd.DataFrame,
    model_choice: str,
) -> None:
    st.title("화면 1 · 전체 분포 및 위험등급 통제 잔차 상위 목록")

    summary = bundle.residual_summary
    res_col = "axis4_residual_b" if model_choice == "model_b" else "axis4_residual_a"
    r2_val = (
        summary.get("model_b", {}).get("r2")
        if model_choice == "model_b"
        else summary.get("model_a", {}).get("r2")
    )

    valid = filtered[filtered[res_col].notna()].copy()
    unmet_any = int((valid["axis4_unmet_count"].fillna(0) > 0).sum())
    unmet_share = (unmet_any / len(valid) * 100) if len(valid) else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "필터 적용 펀드 묶음", f"{len(filtered):,}개", f"회귀 포함 {len(valid):,}개"
    )
    k2.metric("고지 누락 1건 이상 묶음", f"{unmet_any:,}개", f"{unmet_share:.1f}%")
    k3.metric(
        "선택 모형 설명력 (R²)",
        f"{r2_val:.4f}" if isinstance(r2_val, (int, float)) else "-",
        "모형 B 기본" if model_choice == "model_b" else "모형 A 비교",
    )
    k4.metric(
        "파트 B (축 1·2 읽기 난이도)",
        "반영 완료" if bundle.official.get("has_part_b") else "합류 대기",
        "파트 A와 비합산 원칙",
    )

    tab_a, tab_b = st.tabs(
        ["파트 A · 고지 충실도(축 4) 분포 및 잔차", "파트 B · 읽기 난이도(축 1·2)"]
    )

    with tab_a:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("위험등급 × 상품군별 없음 비율 분포")
            chart_df = valid.copy()
            if not chart_df.empty:
                chart_df["상품군"] = chart_df["is_etf"].map(
                    {True: "ETF", False: "공모펀드"}
                )
                chart_df["등급라벨"] = (
                    chart_df["risk_grade"].astype(int).astype(str) + "등급"
                )
                grouped = (
                    chart_df.groupby(["등급라벨", "상품군"], as_index=False)[
                        "axis4_unmet_ratio"
                    ]
                    .mean()
                    .rename(columns={"axis4_unmet_ratio": "평균_없음비율"})
                )
                fig = px.bar(
                    grouped,
                    x="등급라벨",
                    y="평균_없음비율",
                    color="상품군",
                    barmode="group",
                    text_auto=".1%",
                    labels={"등급라벨": "위험등급", "평균_없음비율": "평균 없음 비율"},
                )
                fig.update_yaxes(tickformat=".0%")
                fig.update_layout(
                    height=340, margin={"t": 20, "b": 20, "l": 10, "r": 10}
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("표시할 펀드 묶음이 없습니다.")

        with col_right:
            st.subheader("운용사별 평균 없음 비율 (묶음 3개 이상 상위 15사)")
            if not valid.empty:
                mgr = (
                    valid.groupby("manager", as_index=False)
                    .agg(
                        묶음수=("fund_key", "count"),
                        평균_없음비율=("axis4_unmet_ratio", "mean"),
                    )
                    .query("묶음수 >= 3")
                    .sort_values("평균_없음비율", ascending=False)
                    .head(15)
                )
                if not mgr.empty:
                    fig2 = px.bar(
                        mgr.sort_values("평균_없음비율", ascending=True),
                        x="평균_없음비율",
                        y="manager",
                        orientation="h",
                        text_auto=".1%",
                        hover_data=["묶음수"],
                        labels={"manager": "운용사", "평균_없음비율": "평균 없음 비율"},
                    )
                    fig2.update_xaxes(tickformat=".0%")
                    fig2.update_layout(
                        height=340, margin={"t": 20, "b": 20, "l": 10, "r": 10}
                    )
                    st.plotly_chart(fig2, width="stretch")
                else:
                    st.info("묶음 3개 이상 조건을 만족하는 운용사가 없습니다.")

        st.subheader("위험등급 통제 잔차 상위 목록 (양수일수록 기대 대비 누락 많음)")
        ranked = filtered.sort_values(
            by=[res_col, "axis4_unmet_ratio", "fund_key"],
            ascending=[False, False, True],
            na_position="last",
        ).reset_index(drop=True)
        ranked.insert(0, "순위", range(1, len(ranked) + 1))

        display_df = pd.DataFrame(
            {
                "순위": ranked["순위"],
                "운용사": ranked["manager"],
                "펀드 묶음": ranked["fund_key"],
                "대표접수번호": ranked["rcept_no"].fillna("-"),
                "위험등급": ranked["risk_grade"].map(
                    lambda x: f"{int(x)}등급" if pd.notna(x) else "-"
                ),
                "상품군": ranked["is_etf"].map({True: "ETF", False: "공모펀드"}),
                "있음": ranked["axis4_met_count"],
                "없음": ranked["axis4_unmet_count"],
                "판정불가": ranked["axis4_undetermined_count"],
                "없음비율": ranked["axis4_unmet_ratio"].map(_format_pct),
                "잔차_B(기본)": ranked["axis4_residual_b"].map(_format_num),
                "잔차_A": ranked["axis4_residual_a"].map(_format_num),
                "제외사유": ranked["exclude_reason"].fillna(""),
            }
        )
        st.dataframe(display_df, width="stretch", hide_index=True, height=420)

        act1, act2 = st.columns([3, 1])
        with act1:
            if not ranked.empty:
                fund_uids = (ranked["corp_code"] + "::" + ranked["fund_key"]).tolist()
                label_map = dict(
                    zip(
                        fund_uids,
                        (ranked["manager"] + " | " + ranked["fund_key"]).tolist(),
                        strict=True,
                    )
                )
                chosen_uid = st.selectbox(
                    "상세 화면(화면 2)으로 이동할 펀드 묶음 선택",
                    options=fund_uids,
                    format_func=lambda uid: label_map[uid],
                    key="screen1_drilldown_select",
                )
                if st.button("선택 펀드 상세 드릴다운 열기 → 화면 2", type="primary"):
                    st.session_state["selected_fund_uid"] = chosen_uid
                    st.session_state["_pending_nav_page"] = PAGE_OPTIONS[1]
                    st.rerun()
        with act2:
            csv_bytes = ranked.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "잔차 목록 CSV 내려받기",
                data=csv_bytes,
                file_name="dashboard_residual_ranking.csv",
                mime="text/csv",
            )

    with tab_b:
        if bundle.official.get("has_part_b") and filtered["part_b_score"].notna().any():
            st.dataframe(
                filtered[
                    [
                        "manager",
                        "fund_key",
                        "risk_grade",
                        "axis1_raw",
                        "axis2_raw",
                        "part_b_score",
                        "part_b_percentile",
                        "part_b_residual_b",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "파트 B(축 1 언어 복잡도 · 축 2 용어 부담) 점수 파일이 아직 합류되지 않았습니다. "
                "축 1·2 코드 PR 또는 노트북 CSV(prep-8) 통합 후 같은 파일 계약(`dashboard_documents.parquet`)의 "
                "파트 B 슬롯이 채워지면 자동으로 활성화됩니다. 파트 A(고지 충실도)와 파트 B는 합산하지 않고 "
                "항상 별도 탭으로 표시합니다."
            )


def _render_screen_2(bundle: DashboardBundle, filtered: pd.DataFrame) -> None:
    st.title("화면 2 · 상품 상세 드릴다운")

    all_docs = bundle.documents.sort_values(
        by=["axis4_residual_b", "fund_key"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)
    all_docs["rank_b"] = all_docs["axis4_residual_b"].rank(
        ascending=False, method="min"
    )
    all_docs["fund_uid"] = all_docs["corp_code"] + "::" + all_docs["fund_key"]

    pool = filtered.copy() if not filtered.empty else all_docs.copy()
    pool["fund_uid"] = pool["corp_code"] + "::" + pool["fund_key"]
    options = pool["fund_uid"].tolist()
    label_map = dict(
        zip(
            options,
            (pool["manager"] + " | " + pool["fund_key"]).tolist(),
            strict=True,
        )
    )
    default_uid = st.session_state.get("selected_fund_uid")
    if default_uid not in options:
        default_uid = options[0]

    selected_uid = st.selectbox(
        "펀드 묶음 검색·선택",
        options=options,
        index=options.index(default_uid),
        format_func=lambda uid: label_map[uid],
    )
    st.session_state["selected_fund_uid"] = selected_uid

    doc = all_docs[all_docs["fund_uid"] == selected_uid].iloc[0]
    rank_text = (
        f"{int(doc['rank_b'])}위 / {int(all_docs['axis4_residual_b'].notna().sum())}개"
        if pd.notna(doc["rank_b"])
        else "회귀 제외"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "운용사", str(doc["manager"]), f"묶음 {int(doc['manager_group_count'])}개"
    )
    m2.metric(
        "위험등급 / 상품군",
        f"{int(doc['risk_grade'])}등급" if pd.notna(doc["risk_grade"]) else "등급 없음",
        "ETF" if doc["is_etf"] else "공모펀드",
    )
    m3.metric(
        "모형 B 잔차 (순위)",
        _format_num(doc["axis4_residual_b"]),
        rank_text,
    )
    m4.metric(
        "없음 비율 (모형 A 잔차)",
        _format_pct(doc["axis4_unmet_ratio"]),
        f"모형 A: {_format_num(doc['axis4_residual_a'])}",
    )
    st.caption(
        f"대표 접수번호: `{doc['rcept_no'] or '대표 문서 동률로 미지정'}` · "
        f"제외 사유: `{doc['exclude_reason'] or '없음(회귀 포함)'}`"
    )

    st.divider()
    st.subheader("구역 A · 파트 A — 금소법 제19조 설명의무 10항목 고지 점검")
    st.caption(
        "읽기 난이도(파트 B) 점수와 합산하지 않고 항목별 판정과 근거 문장만 사실 기준으로 표시합니다."
    )

    rcept_no = doc["rcept_no"]
    if pd.isna(rcept_no) or not rcept_no:
        st.warning(
            "최신 접수일에 복수 문서가 동률(`AMBIGUOUS_DOCUMENT`)이라 대표 문서를 고르지 않았습니다."
        )
    else:
        sub = bundle.axis4_judgments[
            bundle.axis4_judgments["rcept_no"] == rcept_no
        ].copy()
        sub["order"] = sub["item"].map({k: i for i, k in enumerate(AXIS4_ITEM_ORDER)})
        sub = sub.sort_values("order")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("있음", int((sub["status"] == "있음").sum()))
        c2.metric("없음", int((sub["status"] == "없음").sum()))
        c3.metric("판정 불가", int((sub["status"] == "판정 불가").sum()))
        c4.metric("적용 대상 아님", int((sub["status"] == "적용 대상 아님").sum()))

        summary_table = pd.DataFrame(
            {
                "항목": sub["item"],
                "점검 내용": sub["item_name"],
                "근거 조문": sub["legal_basis"],
                "판정": sub["status"],
                "근거 절": sub["evidence_sections"].fillna("-"),
            }
        )
        st.dataframe(summary_table, width="stretch", hide_index=True)

        st.markdown("#### 항목별 근거 인용 및 판정 사유")
        for _, row in sub.iterrows():
            status = row["status"]
            label = f"[{status}] {row['item']} {row['item_name']} ({row['evidence_sections'] or '절 정보 없음'})"
            with st.expander(label, expanded=(status in {"없음", "판정 불가"})):
                st.caption(f"근거 조문: {row['legal_basis']}")
                st.write(
                    row["quote_or_reason"] or "기록된 인용 문장 또는 사유가 없습니다."
                )

    st.divider()
    st.subheader("구역 B · 파트 B — 부·절별 읽기 난이도 점수 및 감점 사유")
    if bundle.section_scores is not None and pd.notna(rcept_no):
        sec = bundle.section_scores[
            bundle.section_scores["rcept_no"] == rcept_no
        ].copy()
        if not sec.empty:
            fig = px.bar(
                sec,
                x="section_title",
                y="section_percentile",
                hover_data=["axis1_score", "axis2_score", "deduction_reason"],
                labels={"section_title": "부·절", "section_percentile": "층 내 백분위"},
            )
            st.plotly_chart(fig, width="stretch")
            st.dataframe(
                sec[
                    [
                        "part_no",
                        "section_no",
                        "section_title",
                        "axis1_score",
                        "axis2_score",
                        "section_percentile",
                        "deduction_reason",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("이 문서의 절별 파트 B 점수 행이 아직 없습니다.")
    else:
        st.info(
            "축 1(언어 복잡도)·축 2(용어 부담) 절별 점수 파일(`section_scores.parquet`) 합류 대기 중입니다. "
            "합류 시 이 구역에 부·절별 백분위 차트와 감점 사유 표가 자동으로 표시됩니다."
        )


def _render_screen_3(bundle: DashboardBundle, filtered: pd.DataFrame) -> None:
    st.title("화면 3 · 감점 항목 분해 · 쉬운 문장 변환 · 제재 사례 검증")

    tab1, tab2, tab3 = st.tabs(
        [
            "항목별 누락·감점 분해",
            "쉬운 문장 변환 비교",
            "축 4 제재 사례 검증 표 (탐색 뷰 대체)",
        ]
    )

    with tab1:
        rcepts = set(filtered["rcept_no"].dropna().tolist())
        judg = bundle.axis4_judgments[
            bundle.axis4_judgments["rcept_no"].isin(rcepts)
        ].copy()
        if judg.empty:
            st.info("현재 필터 조건에 해당하는 판정 데이터가 없습니다.")
        else:
            counts = (
                judg.groupby(["item", "status"], as_index=False)
                .size()
                .rename(columns={"size": "건수"})
            )
            totals = judg.groupby("item")["rcept_no"].count().to_dict()
            counts["비율"] = counts.apply(
                lambda r: r["건수"] / totals[r["item"]], axis=1
            )
            counts["항목라벨"] = counts["item"].map(
                lambda k: f"{k} {AXIS4_ITEM_MAP[k]['item_name']}"
            )
            counts["정렬"] = counts["item"].map(
                {k: i for i, k in enumerate(AXIS4_ITEM_ORDER)}
            )
            counts = counts.sort_values("정렬")

            fig = px.bar(
                counts,
                y="항목라벨",
                x="비율",
                color="status",
                orientation="h",
                category_orders={"status": STATUS_ORDER},
                color_discrete_map=STATUS_COLORS,
                hover_data=["건수"],
                labels={"항목라벨": "점검 항목", "비율": "비율", "status": "판정"},
            )
            fig.update_xaxes(tickformat=".0%")
            fig.update_layout(height=420, margin={"t": 20, "b": 20, "l": 10, "r": 10})
            st.plotly_chart(fig, width="stretch")

            st.subheader("특정 항목 「없음」 판정 펀드 조회")
            target_item = st.selectbox(
                "점검 항목 선택",
                options=AXIS4_ITEM_ORDER,
                index=AXIS4_ITEM_ORDER.index("3.3"),
                format_func=lambda k: f"{k} · {AXIS4_ITEM_MAP[k]['item_name']}",
            )
            unmet_rows = judg[
                (judg["item"] == target_item) & (judg["status"] == "없음")
            ].merge(
                filtered[["rcept_no", "manager", "fund_key", "risk_grade", "is_etf"]],
                on="rcept_no",
                how="inner",
            )
            st.caption(f"선택 항목 `{target_item}` 없음 판정: **{len(unmet_rows)}건**")
            st.dataframe(
                unmet_rows[
                    [
                        "manager",
                        "fund_key",
                        "rcept_no",
                        "risk_grade",
                        "evidence_sections",
                        "quote_or_reason",
                    ]
                ].rename(
                    columns={
                        "manager": "운용사",
                        "fund_key": "펀드 묶음",
                        "rcept_no": "접수번호",
                        "risk_grade": "위험등급",
                        "evidence_sections": "근거 절",
                        "quote_or_reason": "판정 사유",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    with tab2:
        st.warning(REWRITE_DISCLAIMER_TEXT)
        sec_df = bundle.section_scores
        if (
            sec_df is not None
            and "simplified_text" in sec_df.columns
            and sec_df["simplified_text"].notna().any()
        ):
            valid_rw = sec_df[
                sec_df["simplified_text"].notna()
                & sec_df["meaning_preserved"].fillna(False).astype(bool)
            ]
            for _, rw in valid_rw.head(20).iterrows():
                st.markdown(f"#### `{rw['rcept_no']}` · {rw['section_title']}")
                left, right = st.columns(2)
                with left:
                    st.caption(
                        f"원문 · 백분위 {rw['section_percentile']:.1f} · LLM 정답률 {_format_pct(rw['llm_acc_before'])}"
                    )
                    st.write(rw["original_excerpt"])
                with right:
                    st.caption(
                        f"쉬운 문장 변환 · 재계산 백분위 {rw['simplified_percentile']:.1f} · "
                        f"LLM 정답률 {_format_pct(rw['llm_acc_after'])}"
                    )
                    st.write(rw["simplified_text"])
                st.divider()
        else:
            st.info(
                "제2부 10절(투자위험)·13절(수수료와 보수) 쉬운 문장 변환 결과(`section_scores.parquet`) "
                "생성 대기 중입니다. 의미 보존 검사(수수료율·위험등급·원금손실 고지·핵심어)를 통과한 "
                "변환문만 원문·재계산 백분위·LLM 정답률 변화와 함께 이 탭에 나란히 표시됩니다."
            )

    with tab3:
        st.caption(
            "분쟁 사례 탐색 뷰를 범위에서 제외하고(11월 28일 PM 결정), "
            "축 4 제재 사례 검증 결과(법인 단위 비교 + 대조군 감사 정밀도)를 표로 제공합니다."
        )
        s_summary = bundle.sanction_summary
        s_df = bundle.sanction_validation

        if s_summary:
            st.info(s_summary.get("firm_level_note", ""))
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric(
                "제재 있음 운용사", f"{s_summary.get('sanctioned_managers', 0)}곳"
            )
            sc2.metric(
                "대조군 후보 운용사", f"{s_summary.get('control_managers', 0)}곳"
            )
            sc3.metric(
                "제재 있음 평균 없음 비율(10항목)",
                _format_pct(s_summary.get("sanctioned_mean_unmet_all_10")),
            )
            sc4.metric(
                "대조군 후보 평균 없음 비율(10항목)",
                _format_pct(s_summary.get("control_mean_unmet_all_10")),
            )

            if s_summary.get("audit_precision_status") == "PENDING":
                st.warning(s_summary.get("audit_precision_note", ""))
            elif s_summary.get("audit_by_item"):
                st.subheader("대조군 감사 표본 정밀도 (Wilson 95% 신뢰구간)")
                st.dataframe(pd.DataFrame(s_summary["audit_by_item"]), width="stretch")

        if s_df is not None and not s_df.empty:
            group_avg = (
                s_df.groupby("group", as_index=False)[
                    [
                        "unmet_ratio_3_2",
                        "unmet_ratio_3_3",
                        "unmet_ratio_3_4",
                        "unmet_ratio_4_1",
                        "unmet_ratio_4_2",
                    ]
                ]
                .mean()
                .melt(id_vars="group", var_name="항목", value_name="평균_없음비율")
            )
            group_avg["항목"] = (
                group_avg["항목"]
                .str.replace("unmet_ratio_", "", regex=False)
                .str.replace("_", ".")
            )
            fig_s = px.bar(
                group_avg,
                x="항목",
                y="평균_없음비율",
                color="group",
                barmode="group",
                text_auto=".1%",
                labels={"group": "집단", "평균_없음비율": "운용사 평균 없음 비율"},
            )
            fig_s.update_yaxes(tickformat=".0%")
            fig_s.update_layout(height=320, margin={"t": 20, "b": 20, "l": 10, "r": 10})
            st.plotly_chart(fig_s, width="stretch")

            st.subheader("운용사별 축 4 제재 대조군 비교 상세 표")
            view_s = pd.DataFrame(
                {
                    "운용사": s_df["manager"],
                    "집단": s_df["group"],
                    "문서수": s_df["document_count"],
                    "3.2": s_df["unmet_ratio_3_2"].map(_format_pct),
                    "3.3": s_df["unmet_ratio_3_3"].map(_format_pct),
                    "3.4": s_df["unmet_ratio_3_4"].map(_format_pct),
                    "4.1": s_df["unmet_ratio_4_1"].map(_format_pct),
                    "4.2": s_df["unmet_ratio_4_2"].map(_format_pct),
                    "판별 5항목": s_df["unmet_ratio_discriminating_5"].map(_format_pct),
                    "전체 10항목": s_df["unmet_ratio_all_10"].map(_format_pct),
                }
            )
            st.dataframe(view_s, width="stretch", hide_index=True)
            st.download_button(
                "제재 검증 비교표 CSV 내려받기",
                data=s_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="axis4_sanction_validation.csv",
                mime="text/csv",
            )
        else:
            st.info("제재 검증 비교 파일(`sanction_validation.parquet`)이 없습니다.")


def main() -> None:
    st.set_page_config(
        page_title="BOAZ Signal · 펀드·ETF 설명 리스크 대시보드",
        layout="wide",
    )

    data_root = resolve_data_root(DEFAULT_LOCAL_ROOT)
    try:
        bundle = _cached_bundle(data_root)
    except (FileNotFoundError, OSError, ValueError, KeyError, RuntimeError) as exc:
        st.error(f"대시보드 내보내기 파일을 불러오지 못했습니다 (`{data_root}`): {exc}")
        st.code(
            "uv run --with-requirements dashboard/requirements.txt python dashboard/build_exports.py \\\n"
            "  --residual-csv ../signal-data/exports/residual/axis4_residual__20261128.csv \\\n"
            "  --residual-json ../signal-data/exports/residual/axis4_residual__20261128.json \\\n"
            "  --judgments-csv ../signal-data/exports/runs/score-20261124T155900Z-7260/axis4_judgments.csv \\\n"
            "  --sanction-csv ../signal-data/exports/axis4_sanction/negative_control__20261125.csv \\\n"
            "  --out-root ../signal-data/exports/dashboard",
            language="bash",
        )
        return

    st.sidebar.title("BOAZ Signal")
    pending_page = st.session_state.pop("_pending_nav_page", None)
    if pending_page in PAGE_OPTIONS:
        st.session_state["nav_page"] = pending_page
    elif "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGE_OPTIONS[0]

    page = st.sidebar.radio(
        "화면 이동",
        options=PAGE_OPTIONS,
        key="nav_page",
    )
    filtered, model_choice, _ = _apply_filters(bundle.documents)
    st.sidebar.divider()
    st.sidebar.caption(
        f"데이터 원천: `{'S3' if data_root.startswith('s3://') else '로컬 파일'}`"
    )

    _render_banner(bundle)

    if page == PAGE_OPTIONS[0]:
        _render_screen_1(bundle, filtered, model_choice)
    elif page == PAGE_OPTIONS[1]:
        _render_screen_2(bundle, filtered)
    else:
        _render_screen_3(bundle, filtered)


if __name__ == "__main__":
    main()

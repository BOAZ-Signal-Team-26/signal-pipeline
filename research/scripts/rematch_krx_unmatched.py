#!/usr/bin/env python3
"""KRX 매칭 실패 229건 재대조 (10월 4일).

용례:
    python3 research/scripts/rematch_krx_unmatched.py <공공데이터포털 전체 캐시 JSON> <결과 CSV>

입력: research/samples/etf_rule_check.csv 의 「KRX매칭실패」 행, verify_etf_rule.py --cache 로 받은 포털 전체 JSON,
      그리고 결과 CSV 자체(이미 있으면 사람이 확정한 행과 보류 메모를 읽어 유지함).
결과 CSV의 `결과` 칸: 자동 1:1 / 확정(사람 확인) / 보류. 사람이 판단을 바꾸려면 이 파일의 해당 행을 직접 고침.
규칙은 docs/matching-rules.md 「KRX 매칭 실패 처리」.
"""
import csv,json,re,sys,collections
sys.path.insert(0,'research/scripts'); from verify_etf_rule import normalize as N
r=[x for x in csv.DictReader(open('research/samples/etf_rule_check.csv',encoding='utf-8')) if x['구분']=='KRX매칭실패']
d=json.load(open(sys.argv[1],encoding='utf-8'))
F={}
for f in d:
    if '상장지수' in f['fndNm'] or 'ETF' in f['fndNm'].upper():
        F.setdefault(f['srtnCd'],f)  # one row per short code
F=list(F.values()); FN=[(N(re.sub(r'\([^)]*\)|\[[^\]]*\]','',f['fndNm'])),f) for f in F]
# 수식어 제거: KRX 괄호 표기((합성)·(H)·(합성 H)) — 포털은 이 표기를 이름 끝에 따로 붙이거나 생략
ALIAS={'ACE':['KINDEX'],'RISE':['KBSTAR'],'PLUS':['ARIRANG'],'KIWOOM':['KOSEF'],'1Q':[],'SOL':[],'KODEX':[],'TIGER':[],'HANARO':[]}
TAILS=['증권','특별자산','상장지수','파생','부동산','채권','주식','혼합','투자신탁','재간접','금리','통화','원자재']
def keys(name):
    base=re.sub(r'\([^)]*\)','',name).strip(); b=base.split()[0]; rest=base[len(b):]
    ks=[N(base)]+[N(a+rest) for a in ALIAS.get(b,[])]
    ks+= [k[:-2]+'TOTALRETURN' for k in ks if k.endswith('TR')]  # 포털은 TR을 Total Return으로 풀어 씀
    return ks
def hit(k):
    out=[]
    for n,f in FN:
        i=n.find(k)
        if i<0: continue
        tail=n[i+len(k):]
        if tail=='' or any(tail.startswith(t) for t in TAILS): out.append(f)
    return out
stat=collections.Counter(); rows=[]
for x in r:
    found=[]
    for k in keys(x['KRX종목명']):
        found=hit(k)
        # 환헤지 표기가 다르면 후보에서 뺌(후보 1개여도): KRX (H)·(합성 H) ↔ 포털 이름의 (H)·(합성 H)
        # 예: KRX `PLUS 미국S&P500(H)`가 포털의 환노출형 `한화 PLUS 미국S&P500`에 붙지 않게 함
        h='H)' in x['KRX종목명']
        found=[f for f in found if ('(H)' in f['fndNm'] or '(합성H)' in f['fndNm'].replace(' ',''))==h]
        if found: break
    st='자동 1:1' if len(found)==1 else ('후보 여러 개' if found else '후보 없음')
    stat[st]+=1
    rows.append([st,x['ISU_CD'],x['KRX종목명'],len(found)]+([found[0]['fndNm'],found[0]['srtnCd'],found[0]['asoStdCd']] if len(found)==1 else ['','','']))
print('1차',dict(stat))

# 2차: 같은 브랜드 안에서 핵심 이름 유사도(사람 확인용 후보)
import difflib
BR={'ACE':['ACE','KINDEX'],'RISE':['RISE','KBSTAR'],'PLUS':['PLUS','ARIRANG'],'KIWOOM':['KIWOOM','KOSEF'],'KODEX':['KODEX'],'TIGER':['TIGER'],'SOL':['SOL'],'HANARO':['HANARO'],'1Q':['1Q'],'FOCUS':['FOCUS'],'마이티':['마이티'],'파워':['파워']}
def core(n):
    n=re.split(r'(증권상장|특별자산상장|부동산상장|상장지수|증권투자신탁)',n)[0]  # 상품명 안의 「부동산」 등에서 자르지 않음
    return n.replace('적격','').replace('플러스','+')
stat2=collections.Counter(); out=[]
for row in rows:
    if row[0]=='자동 1:1': out.append(row+['']); continue
    nm=row[2]; b=nm.split()[0]; brands=BR.get(b,[b])
    k=core(N(re.sub(r'\([^)]*\)','',nm[len(b):]))).replace('+','')
    best=[]
    for n,f in FN:
        bi=[n.find(N(x)) for x in brands if N(x) in n]
        if not bi: continue
        c=core(n[min(bi)+len(N(brands[0])) if N(brands[0]) in n else min(bi):]).replace('+','')
        for x in brands: c=c.replace(N(x),'')
        best.append((difflib.SequenceMatcher(None,k,c).ratio(),f))
    best.sort(key=lambda t:-t[0])
    if best and best[0][0]>=0.85 and (len(best)<2 or best[0][0]-best[1][0]>=0.05):
        st='유사도 후보(확인 필요)'; f=best[0][1]
        out.append([st,row[1],nm,row[3],f['fndNm'],f['srtnCd'],f['asoStdCd'],round(best[0][0],2)])
    else:
        st='수동'; out.append([st,row[1],nm,row[3],'','','',round(best[0][0],2) if best else 0])
    stat2[st]+=1
# 사람의 판단은 결과 파일 자체에 남김. 결과 파일이 이미 있으면 「확정(사람 확인)」 행과 「보류」 행의 메모를 유지하고,
# 규칙으로 새로 붙는 「자동 1:1」 행만 다시 계산함(규칙을 고치면 자동 행이 바뀔 수 있음)
import os
prev={}
if os.path.exists(sys.argv[2]):
    for c in csv.DictReader(open(sys.argv[2],encoding='utf-8')): prev[c['ISU_CD']]=c
final=[]
for o in out:
    c=prev.get(o[1])
    if o[0]=='자동 1:1': final.append(o+[c['메모'] if c else ''])  # 자동 행의 점검 메모도 유지
    elif c and c['결과']=='확정(사람 확인)':
        final.append(['확정(사람 확인)',o[1],o[2],1,c['포털펀드명'],c['srtnCd'],c['asoStdCd'],c['유사도'],c['메모']])
    else: final.append(['보류',o[1],o[2],o[3],'','','',o[7] if len(o)>7 else '',c['메모'] if c else ''])
out=final
print('최종',dict(collections.Counter(o[0] for o in out)))
print('2차',stat2)
csv.writer(open(sys.argv[2],'w',newline='',encoding='utf-8'),lineterminator='\n').writerows([['결과','ISU_CD','KRX종목명','후보수','포털펀드명','srtnCd','asoStdCd','유사도','메모']]+out)

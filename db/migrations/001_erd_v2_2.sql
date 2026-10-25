-- ERD v2.2 (docs/schema.dbml) 물리 DDL. PostgreSQL 16.
-- 물리 결정 6건은 docs/data-model.md 「물리 결정」 참조.
-- 다시 실행해도 변화가 없도록 IF NOT EXISTS만 사용한다. 이미 있는 표의 정의는 바꾸지 않는다.
-- 표 이름은 모두 스키마를 붙여 쓴다. 실행 계정의 검색 경로(search_path)와 무관하게 같은 곳에 만든다.

create schema if not exists raw;
create schema if not exists staging;
create schema if not exists mart;

create table if not exists staging.distributor (
  distributor_id bigint generated always as identity primary key,
  kofia_sales_code varchar(6) unique,
  corp_code text,
  kofia_disclosure_company_code varchar(6) unique,
  kofia_mgmt_code varchar(3),
  distributor_name text not null,
  distributor_name_normalized text,
  distributor_type text not null constraint distributor_distributor_type_check check (distributor_type in ('운용사', '판매사', '겸업', '미상'))
);

create table if not exists raw.document (
  document_id bigint generated always as identity primary key,
  source text not null,
  source_doc_key text not null,
  source_key_payload jsonb not null,
  source_record_payload jsonb,
  action_date date,
  source_input_at timestamptz,
  rcept_no varchar(14),
  dcm_no text,
  corp_code text,
  document_type text not null constraint document_document_type_check check (document_type in ('투자설명서', '간이투자설명서', '일괄신고서', '효력발생안내', '제재공시', '분쟁조정결정문', '금투협 수시공시', '경영유의공시')),
  report_name text,
  report_base_date date,
  distributor_id bigint, -- staging.distributor 참조. raw 단독 복원을 위해 외래 키 없이 db/checks/document_distributor.sql로 검증
  is_correction boolean,
  lineage_id bigint,
  version_no integer,
  is_current boolean,
  initial_submit_date date,
  received_date date not null,
  constraint document_source_key unique (source, source_doc_key),
  constraint document_lineage_id_fkey foreign key (lineage_id) references raw.document (document_id),
  constraint document_rcept_no_format_check check (rcept_no ~ '^[0-9]{14}$')
);

create table if not exists raw.raw_object (
  raw_object_id bigint generated always as identity primary key,
  document_id bigint,
  source text not null,
  source_object_key text not null,
  version_seq integer not null,
  body_format text not null constraint raw_object_body_format_check check (body_format in ('html', 'json', 'xml', 'zip', 'unknown', 'pdf', 'hwp5', 'hwp3', 'hwp_dist', 'xml_only')),
  original_file_name text,
  server_path text,
  download_url text,
  source_baseline_date date,
  file_role text not null constraint raw_object_file_role_check check (file_role in ('cover_html', 'cover_xml', 'body_pdf', 'api_response', 'attachment', 'prospectus', 'prospectus_simple', 'change_summary')),
  sha256 varchar(64) not null,
  storage_path text not null,
  blob_path text,
  file_name text not null,
  content_type text,
  collected_at timestamptz not null,
  request_params jsonb not null,
  response_code text,
  collect_status text not null constraint raw_object_collect_status_check check (collect_status in ('success', 'failed', 'permanent_failed')),
  constraint raw_object_source_key unique (source, source_object_key, version_seq),
  constraint raw_object_raw_object_id_key unique (raw_object_id, document_id),
  constraint raw_object_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint raw_object_version_seq_positive_check check (version_seq >= 1)
);

create index if not exists raw_object_document_id_idx on raw.raw_object (document_id);

create table if not exists raw.pipeline_run (
  run_id text primary key,
  run_kind text not null constraint pipeline_run_run_kind_check check (run_kind in ('EXTRACT', 'SCORE')),
  upstream_run_id text,
  is_official boolean not null default false,
  published_at timestamptz,
  baseline_date date not null,
  status text not null constraint pipeline_run_status_check check (status in ('PLANNED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  config_manifest jsonb not null,
  config_sha256 varchar(64) not null,
  input_manifest_path text,
  input_manifest_sha256 varchar(64),
  selection_manifest_path text,
  selection_manifest_sha256 varchar(64),
  started_at timestamptz not null,
  completed_at timestamptz,
  constraint pipeline_run_upstream_run_id_fkey foreign key (upstream_run_id) references raw.pipeline_run (run_id),
  constraint pipeline_run_upstream_by_kind_check check ((run_kind = 'SCORE' and upstream_run_id is not null) or (run_kind = 'EXTRACT' and upstream_run_id is null)),
  constraint pipeline_run_official_only_succeeded_score_check check (not is_official or (run_kind = 'SCORE' and status = 'SUCCEEDED')),
  constraint pipeline_run_selection_manifest_pair_check check ((selection_manifest_path is null) = (selection_manifest_sha256 is null)),
  constraint pipeline_run_extract_has_no_selection_manifest_check check (run_kind = 'SCORE' or selection_manifest_path is null)
);

create table if not exists raw.collection_attempt (
  attempt_id bigint generated always as identity primary key,
  run_id text not null,
  source text not null,
  request_key text not null,
  attempt_no integer not null,
  endpoint text not null,
  request_params jsonb not null,
  document_id bigint,
  raw_object_id bigint,
  http_status integer,
  source_result_code text,
  result_count integer,
  outcome text not null constraint collection_attempt_outcome_check check (outcome in ('SUCCESS', 'EMPTY', 'RETRYABLE_FAILED', 'PERMANENT_FAILED', 'CONFIG_ERROR', 'RATE_LIMITED', 'STARTED')),
  error_reason text,
  attempted_at timestamptz not null,
  constraint collection_attempt_run_id_key unique (run_id, request_key, attempt_no),
  constraint collection_attempt_run_id_fkey foreign key (run_id) references raw.pipeline_run (run_id),
  constraint collection_attempt_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint collection_attempt_raw_object_id_fkey foreign key (raw_object_id) references raw.raw_object (raw_object_id),
  constraint collection_attempt_attempt_no_positive_check check (attempt_no >= 1)
);

create table if not exists staging.file_extraction (
  raw_object_id bigint not null,
  parser_version text not null,
  created_run_id text not null,
  extract_status text not null constraint file_extraction_extract_status_check check (extract_status in ('EXTRACT_OK', 'EXTRACT_FAILED', 'EXTRACT_UNSUPPORTED_FORMAT', 'EXTRACT_PARTIAL', 'OCR_CANDIDATE', 'EXTRACT_NOT_APPLICABLE', 'SECTION_BOUNDARY_NOT_FOUND')),
  canonical_text_path text,
  canonical_text_sha256 varchar(64),
  structure_manifest_path text,
  structure_manifest_sha256 varchar(64),
  structure_status text not null constraint file_extraction_structure_status_check check (structure_status in ('AVAILABLE', 'PARTIAL', 'UNAVAILABLE', 'NOT_REQUESTED')),
  text_length integer,
  error_reason text,
  extracted_at timestamptz not null,
  primary key (raw_object_id, parser_version),
  constraint file_extraction_raw_object_id_fkey foreign key (raw_object_id) references raw.raw_object (raw_object_id),
  constraint file_extraction_created_run_id_fkey foreign key (created_run_id) references raw.pipeline_run (run_id),
  constraint file_extraction_ok_needs_text_check check (extract_status <> 'EXTRACT_OK' or (canonical_text_path is not null and canonical_text_sha256 is not null and text_length is not null)),
  constraint file_extraction_structure_manifest_required_check check ((structure_status in ('AVAILABLE','PARTIAL') or (extract_status = 'EXTRACT_OK' and structure_status = 'UNAVAILABLE')) = (structure_manifest_path is not null)),
  constraint file_extraction_structure_manifest_pair_check check ((structure_manifest_path is null) = (structure_manifest_sha256 is null)),
  constraint file_extraction_text_length_nonnegative_check check (text_length >= 0),
  constraint file_extraction_extract_status_not_boundary_check check (extract_status <> 'SECTION_BOUNDARY_NOT_FOUND'),
  constraint file_extraction_parser_version_format_check check (parser_version ~ '^[a-z0-9._-]+$')
);

create index if not exists file_extraction_created_run_id_idx on staging.file_extraction (created_run_id);

create table if not exists mart.metric_definition (
  metric_key text primary key,
  metric_id text not null,
  version text not null,
  target_type text not null constraint metric_definition_target_type_check check (target_type in ('SECTION', 'DOCUMENT', 'DOCUMENT_PAIR', 'FUND')),
  level text not null constraint metric_definition_level_check check (level in ('ATOMIC', 'AXIS', 'COMPOSITE', 'TRANSFORM')),
  direction text not null constraint metric_definition_direction_check check (direction in ('HIGHER_IS_HARDER', 'HIGHER_IS_BETTER', 'NONE')),
  definition_status text not null constraint metric_definition_definition_status_check check (definition_status in ('DRAFT', 'APPROVED', 'RETIRED')),
  definition_manifest jsonb not null,
  definition_sha256 varchar(64) not null,
  constraint metric_definition_metric_id_key unique (metric_id, version),
  constraint metric_definition_metric_key_key unique (metric_key, target_type)
);

create table if not exists raw.source_watermark (
  source text not null,
  scope_key text not null,
  covered_from date not null,
  covered_through date not null,
  verified_run_id text not null,
  verification_note text,
  updated_at timestamptz not null,
  primary key (source, scope_key),
  constraint source_watermark_verified_run_id_fkey foreign key (verified_run_id) references raw.pipeline_run (run_id)
);

create index if not exists source_watermark_verified_run_id_idx on raw.source_watermark (verified_run_id);

create table if not exists staging.section (
  section_id bigint generated always as identity primary key,
  document_id bigint not null,
  raw_object_id bigint not null,
  parser_version text not null,
  section_seq integer not null,
  part_seq integer,
  source_section_no text,
  canonical_section_code text,
  section_kind text not null constraint section_section_kind_check check (section_kind in ('body', 'summary', 'other')),
  char_start integer,
  char_end integer,
  quality_flags jsonb,
  section_title text,
  section_text text,
  extract_status text not null constraint section_extract_status_check check (extract_status in ('EXTRACT_OK', 'EXTRACT_FAILED', 'EXTRACT_UNSUPPORTED_FORMAT', 'EXTRACT_PARTIAL', 'OCR_CANDIDATE', 'EXTRACT_NOT_APPLICABLE', 'SECTION_BOUNDARY_NOT_FOUND')),
  constraint section_raw_object_id_key unique (raw_object_id, parser_version, section_seq),
  constraint section_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint section_raw_object_id_parser_version_fkey foreign key (raw_object_id, parser_version) references staging.file_extraction (raw_object_id, parser_version),
  constraint section_raw_object_id_document_id_fkey foreign key (raw_object_id, document_id) references raw.raw_object (raw_object_id, document_id),
  constraint section_char_range_check check ((char_start is null and char_end is null) or (char_start is not null and char_end is not null and char_start >= 0 and char_start < char_end)),
  constraint section_boundary_not_found_has_no_range_check check (extract_status <> 'SECTION_BOUNDARY_NOT_FOUND' or (char_start is null and char_end is null)),
  constraint section_parser_version_format_check check (parser_version ~ '^[a-z0-9._-]+$')
);

create index if not exists section_document_id_idx on staging.section (document_id);

create table if not exists staging.fund_group (
  fund_key text primary key,
  canonical_name text not null,
  manager_id bigint not null,
  created_run_id text not null,
  grouping_evidence jsonb not null,
  representative_risk_grade integer,
  risk_grade_source_document_id bigint,
  risk_grade_source_kind text constraint fund_group_risk_grade_source_kind_check check (risk_grade_source_kind in ('SIMPLE_PROSPECTUS_TITLE', 'PROSPECTUS_COVER')),
  constraint fund_group_manager_id_fkey foreign key (manager_id) references staging.distributor (distributor_id),
  constraint fund_group_created_run_id_fkey foreign key (created_run_id) references raw.pipeline_run (run_id),
  constraint fund_group_risk_grade_source_document_id_fkey foreign key (risk_grade_source_document_id) references raw.document (document_id),
  constraint fund_group_representative_risk_grade_range_check check (representative_risk_grade between 1 and 6),
  constraint fund_group_risk_grade_needs_source_check check (representative_risk_grade is null or (risk_grade_source_document_id is not null and risk_grade_source_kind is not null))
);

create index if not exists fund_group_risk_grade_source_document_id_idx on staging.fund_group (risk_grade_source_document_id);
create index if not exists fund_group_created_run_id_idx on staging.fund_group (created_run_id);

create table if not exists mart.population_snapshot (
  population_snapshot_id bigint generated always as identity primary key,
  run_id text not null,
  baseline_date date not null,
  population_key text not null,
  observation_unit text not null constraint population_snapshot_observation_unit_check check (observation_unit in ('fund_document', 'fund_section')),
  metric_key text not null,
  product_category text not null constraint population_snapshot_product_category_check check (product_category in ('펀드', 'ETF', 'ELS')),
  risk_grade integer,
  fund_type text,
  product_class_code text,
  stratification_definition jsonb not null,
  member_count integer not null,
  minimum_member_count integer not null,
  excluded_count integer not null,
  exclusion_counts jsonb not null,
  membership_manifest_path text not null,
  membership_manifest_sha256 varchar(64) not null,
  computed_at timestamptz not null,
  constraint population_snapshot_run_id_key unique (run_id, metric_key, population_key),
  constraint population_snapshot_population_snapshot_id_key unique (population_snapshot_id, run_id, metric_key),
  constraint population_snapshot_run_id_fkey foreign key (run_id) references raw.pipeline_run (run_id),
  constraint population_snapshot_metric_key_fkey foreign key (metric_key) references mart.metric_definition (metric_key),
  constraint population_snapshot_counts_nonnegative_check check (member_count >= 0 and minimum_member_count >= 0 and excluded_count >= 0)
);

create table if not exists staging.llm_field_extraction (
  extraction_id bigint generated always as identity primary key,
  run_id text not null,
  document_id bigint not null,
  raw_object_id bigint,
  field_name text not null,
  attempt_no integer not null,
  model_name text not null,
  prompt_sha256 varchar(64) not null,
  input_sha256 varchar(64) not null,
  input_tokens integer,
  output_tokens integer,
  result_status text not null constraint llm_field_extraction_result_status_check check (result_status in ('PENDING', 'OK', 'NOT_APPLICABLE', 'UNDETERMINED', 'FAILED')),
  value_json jsonb,
  evidence_section_id bigint,
  evidence_char_start integer,
  evidence_char_end integer,
  model_params jsonb,
  raw_response_path text,
  response_sha256 varchar(64),
  is_selected boolean not null default false,
  error_reason text,
  extracted_at timestamptz not null,
  constraint llm_field_extraction_run_id_key unique (run_id, document_id, field_name, attempt_no),
  constraint llm_field_extraction_run_id_fkey foreign key (run_id) references raw.pipeline_run (run_id),
  constraint llm_field_extraction_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint llm_field_extraction_raw_object_id_fkey foreign key (raw_object_id) references raw.raw_object (raw_object_id),
  constraint llm_field_extraction_evidence_section_id_fkey foreign key (evidence_section_id) references staging.section (section_id),
  constraint llm_field_extraction_attempt_no_positive_check check (attempt_no >= 1),
  constraint llm_field_extraction_ok_needs_value_check check (result_status <> 'OK' or value_json is not null),
  constraint llm_field_extraction_evidence_range_check check ((evidence_char_start is null and evidence_char_end is null) or (evidence_section_id is not null and evidence_char_start is not null and evidence_char_end is not null and evidence_char_start >= 0 and evidence_char_start < evidence_char_end))
);

create index if not exists llm_field_extraction_document_id_idx on staging.llm_field_extraction (document_id, field_name, input_sha256, prompt_sha256);
create index if not exists llm_field_extraction_evidence_section_id_idx on staging.llm_field_extraction (evidence_section_id);

create table if not exists staging.product (
  product_id bigint generated always as identity primary key,
  short_code varchar(5),
  std_code_scheme text constraint product_std_code_scheme_check check (std_code_scheme in ('K55', 'KR5', 'KRM', 'OTHER')),
  std_code varchar(12),
  isu_cd text,
  product_name text not null,
  product_name_normalized text,
  product_category text constraint product_product_category_check check (product_category in ('펀드', 'ETF', 'ELS')),
  is_etf boolean,
  etf_confidence text not null constraint product_etf_confidence_check check (etf_confidence in ('KRX_CONFIRMED', 'NAME_ONLY', 'NOT_ETF', 'PENDING')),
  fund_key text,
  risk_grade integer,
  manager_id bigint,
  inception_date date,
  fund_type text,
  product_class_code text,
  source_raw_object_id bigint,
  source_baseline_date date,
  risk_grade_raw_object_id bigint,
  valid_from date,
  valid_to date,
  constraint product_fund_key_fkey foreign key (fund_key) references staging.fund_group (fund_key),
  constraint product_manager_id_fkey foreign key (manager_id) references staging.distributor (distributor_id),
  constraint product_source_raw_object_id_fkey foreign key (source_raw_object_id) references raw.raw_object (raw_object_id),
  constraint product_risk_grade_raw_object_id_fkey foreign key (risk_grade_raw_object_id) references raw.raw_object (raw_object_id),
  constraint product_short_code_format_check check (short_code ~ '^[A-Z0-9]{5}$'),
  constraint product_risk_grade_range_check check (risk_grade between 1 and 6),
  constraint product_is_etf_matches_confidence_check check (is_etf is not distinct from (case etf_confidence when 'KRX_CONFIRMED' then true when 'NOT_ETF' then false end)),
  constraint product_std_code_scheme_needs_code_check check (std_code is not null or std_code_scheme is null),
  constraint product_valid_period_check check (valid_from is null or valid_to is null or valid_from <= valid_to)
);

create index if not exists product_short_code_idx on staging.product (short_code);
create index if not exists product_fund_key_idx on staging.product (fund_key);

create table if not exists staging.product_distributor (
  product_id bigint not null,
  distributor_id bigint not null,
  snapshot_month varchar(6) not null,
  source_raw_object_id bigint not null,
  observed_date date not null,
  source_document_id bigint,
  primary key (product_id, distributor_id, snapshot_month),
  constraint product_distributor_product_id_fkey foreign key (product_id) references staging.product (product_id),
  constraint product_distributor_distributor_id_fkey foreign key (distributor_id) references staging.distributor (distributor_id),
  constraint product_distributor_source_raw_object_id_fkey foreign key (source_raw_object_id) references raw.raw_object (raw_object_id),
  constraint product_distributor_source_document_id_fkey foreign key (source_document_id) references raw.document (document_id),
  constraint product_distributor_snapshot_month_format_check check (snapshot_month ~ '^[0-9]{6}$')
);

create table if not exists staging.document_product (
  document_id bigint not null,
  product_id bigint not null,
  match_method text not null constraint document_product_match_method_check check (match_method in ('code', 'string', 'manual')),
  match_score numeric,
  matched_at timestamptz not null,
  primary key (document_id, product_id),
  constraint document_product_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint document_product_product_id_fkey foreign key (product_id) references staging.product (product_id)
);

create index if not exists document_product_product_id_idx on staging.document_product (product_id);

create table if not exists mart.score (
  score_id bigint generated always as identity primary key,
  run_id text not null,
  target_type text not null constraint score_target_type_check check (target_type in ('SECTION', 'DOCUMENT', 'DOCUMENT_PAIR', 'FUND')),
  target_key varchar(64) not null,
  section_id bigint,
  document_id bigint,
  fund_key text,
  metric_key text not null,
  assessor_key text not null,
  result_status text not null constraint score_result_status_check check (result_status in ('PENDING', 'OK', 'NOT_APPLICABLE', 'UNDETERMINED', 'FAILED')),
  reason_code text,
  raw_score numeric,
  numerator numeric,
  denominator numeric,
  normalized_score numeric,
  normalization_status text not null constraint score_normalization_status_check check (normalization_status in ('OK', 'NOT_REQUESTED', 'UNAVAILABLE')),
  normalization_reason text,
  population_snapshot_id bigint,
  score_payload jsonb not null,
  scored_at timestamptz not null,
  constraint score_run_id_key unique (run_id, target_key, metric_key, assessor_key),
  constraint score_run_id_fkey foreign key (run_id) references raw.pipeline_run (run_id),
  constraint score_section_id_fkey foreign key (section_id) references staging.section (section_id),
  constraint score_document_id_fkey foreign key (document_id) references raw.document (document_id),
  constraint score_fund_key_fkey foreign key (fund_key) references staging.fund_group (fund_key),
  constraint score_population_snapshot_id_run_id_metric_key_fkey foreign key (population_snapshot_id, run_id, metric_key) references mart.population_snapshot (population_snapshot_id, run_id, metric_key),
  constraint score_metric_key_target_type_fkey foreign key (metric_key, target_type) references mart.metric_definition (metric_key, target_type),
  constraint score_target_column_matches_type_check check (case target_type when 'SECTION' then section_id is not null and document_id is null and fund_key is null when 'DOCUMENT' then document_id is not null and section_id is null and fund_key is null when 'FUND' then fund_key is not null and section_id is null and document_id is null else false end),
  constraint score_exactly_one_target_check check (num_nonnulls(section_id, document_id, fund_key) = 1),
  constraint score_raw_score_only_when_ok_check check ((result_status = 'OK') = (raw_score is not null)),
  constraint score_reason_required_unless_ok_check check (result_status = 'OK' or reason_code is not null),
  constraint score_normalization_state_check check (case normalization_status when 'OK' then result_status = 'OK' and normalized_score is not null and population_snapshot_id is not null when 'NOT_REQUESTED' then normalized_score is null and population_snapshot_id is null and normalization_reason is null when 'UNAVAILABLE' then normalized_score is null and normalization_reason is not null end)
);

create index if not exists score_section_id_idx on mart.score (section_id);
create index if not exists score_document_id_idx on mart.score (document_id);
create index if not exists score_fund_key_idx on mart.score (fund_key);

create table if not exists staging.match_failure (
  failure_id bigint generated always as identity primary key,
  run_id text not null,
  target_type text not null constraint match_failure_target_type_check check (target_type in ('product', 'distributor')),
  top1_candidate_distributor_id bigint,
  resolved_at timestamptz,
  resolution_note text,
  source text not null,
  attempted_key_value text not null,
  normalized_value text,
  top1_candidate_product_id bigint,
  top1_similarity numeric,
  failure_reason_code text not null constraint match_failure_failure_reason_code_check check (failure_reason_code in ('PENDING_MASTER', 'AMBIGUOUS', 'NO_CANDIDATE', 'NO_CODE_IN_SOURCE', 'BELOW_THRESHOLD', 'NORMALIZE_FAILED', 'CLASS_GRADE_MISMATCH', 'OUT_OF_SCOPE_SECTOR', 'NOT_IN_MASTER')),
  attempted_at timestamptz not null,
  status text not null constraint match_failure_status_check check (status in ('미해결', '수동확인중', '보류', '해결', '대상외')),
  related_document_id bigint,
  constraint match_failure_run_id_fkey foreign key (run_id) references raw.pipeline_run (run_id),
  constraint match_failure_top1_candidate_distributor_id_fkey foreign key (top1_candidate_distributor_id) references staging.distributor (distributor_id),
  constraint match_failure_top1_candidate_product_id_fkey foreign key (top1_candidate_product_id) references staging.product (product_id),
  constraint match_failure_related_document_id_fkey foreign key (related_document_id) references raw.document (document_id)
);

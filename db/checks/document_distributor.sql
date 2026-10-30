-- raw.document.distributor_id가 staging.distributor에 없는 행. 0행이어야 한다.
-- 외래 키 대신 쓰는 검증(docs/data-model.md 「물리 결정」 6). 적재 뒤 실행해 1행 이상이면 적재 실패로 기록한다.
select d.document_id, d.distributor_id
from raw.document d
left join staging.distributor s on s.distributor_id = d.distributor_id
where d.distributor_id is not null and s.distributor_id is null;

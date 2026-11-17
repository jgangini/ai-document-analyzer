CREATE TABLE ingest_jobs (
    ingest_jobs_id           NUMBER NOT NULL,
    user_id                  NUMBER NOT NULL,
    ingest_jobs_status       VARCHAR2(40) NOT NULL,
    ingest_jobs_source_path  VARCHAR2(1000),
    ingest_jobs_include_archives NUMBER DEFAULT 1 NOT NULL,
    ingest_jobs_request_limit NUMBER,
    ingest_jobs_error_message CLOB,
    ingest_jobs_updated      TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    ingest_jobs_created      TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_ingest_jobs_id PRIMARY KEY (ingest_jobs_id),
    CONSTRAINT fk_ingest_jobs_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE ingest_jobs_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_ingest_jobs_id
    BEFORE INSERT ON ingest_jobs
    FOR EACH ROW
    WHEN (NEW.ingest_jobs_id IS NULL)
BEGIN
    :NEW.ingest_jobs_id := ingest_jobs_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_ingest_jobs_updated
BEFORE UPDATE ON ingest_jobs
FOR EACH ROW
BEGIN
    :NEW.ingest_jobs_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX ingest_jobs_idx1
    ON ingest_jobs (user_id, ingest_jobs_status, ingest_jobs_updated);
--

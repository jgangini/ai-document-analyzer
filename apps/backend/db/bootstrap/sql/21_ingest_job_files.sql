CREATE TABLE ingest_job_files (
    ingest_job_files_id            NUMBER NOT NULL,
    ingest_jobs_id                 NUMBER NOT NULL,
    file_id                        NUMBER NULL,
    ingest_job_files_file_name     VARCHAR2(500),
    ingest_job_files_status        VARCHAR2(40) NOT NULL,
    ingest_job_files_details       CLOB,
    ingest_job_files_updated       TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    ingest_job_files_created       TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_ingest_job_files_id PRIMARY KEY (ingest_job_files_id),
    CONSTRAINT fk_ingest_job_files_job FOREIGN KEY (ingest_jobs_id)
        REFERENCES ingest_jobs(ingest_jobs_id) ON DELETE CASCADE,
    CONSTRAINT fk_ingest_job_files_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE ingest_job_files_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_ingest_job_files_id
    BEFORE INSERT ON ingest_job_files
    FOR EACH ROW
    WHEN (NEW.ingest_job_files_id IS NULL)
BEGIN
    :NEW.ingest_job_files_id := ingest_job_files_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_ingest_job_files_updated
BEFORE UPDATE ON ingest_job_files
FOR EACH ROW
BEGIN
    :NEW.ingest_job_files_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX ingest_job_files_idx1
    ON ingest_job_files (ingest_jobs_id, ingest_job_files_status, ingest_job_files_updated);
--

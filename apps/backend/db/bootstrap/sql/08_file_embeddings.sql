CREATE TABLE file_embeddings (
    file_embeddings_id              NUMBER NOT NULL,
    user_id                         NUMBER NOT NULL,
    file_id                         NUMBER NOT NULL,
    archive_slug                    VARCHAR2(256),
    file_embeddings_model           VARCHAR2(255) NOT NULL,
    file_embeddings_dimension       NUMBER NOT NULL,
    file_embeddings_vector          VECTOR(768, FLOAT32),
    file_embeddings_summary         CLOB DEFAULT '' NOT NULL,
    file_embeddings_search_text     CLOB DEFAULT '' NOT NULL,
    file_embeddings_updated         TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_embeddings_created         TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_embeddings_id PRIMARY KEY (file_embeddings_id),
    CONSTRAINT fk_file_embeddings_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_embeddings_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT uq_file_embeddings_file UNIQUE (file_id)
);
--

CREATE SEQUENCE file_embeddings_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_embeddings_id
    BEFORE INSERT ON file_embeddings
    FOR EACH ROW
    WHEN (NEW.file_embeddings_id IS NULL)
BEGIN
    :NEW.file_embeddings_id := file_embeddings_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_embeddings_updated
BEFORE UPDATE ON file_embeddings
FOR EACH ROW
BEGIN
    :NEW.file_embeddings_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_embeddings_user_file
    ON file_embeddings (user_id, file_id);
--

CREATE INDEX idx_file_embeddings_archive
    ON file_embeddings (user_id, archive_slug);
--

CREATE INDEX idx_file_embeddings_search_text
    ON file_embeddings (file_embeddings_search_text)
    INDEXTYPE IS CTXSYS.CONTEXT
    PARAMETERS ('MAINTENANCE AUTO');
--

-- Use neighbor partitions so embeddings remain writable on ADB deployments
-- that still run with COMPATIBLE 23.5 during iterative ingestion.
CREATE VECTOR INDEX idx_file_embeddings_vector
    ON file_embeddings (file_embeddings_vector)
    INCLUDE (user_id, file_id, archive_slug)
    ORGANIZATION NEIGHBOR PARTITIONS
    WITH TARGET ACCURACY 95;
--

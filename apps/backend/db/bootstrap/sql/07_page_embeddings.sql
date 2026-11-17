CREATE TABLE page_embeddings (
    page_embeddings_id          NUMBER NOT NULL,
    user_id                     NUMBER NOT NULL,
    file_id                     NUMBER NOT NULL,
    file_pages_id               NUMBER NOT NULL,
    archive_slug                VARCHAR2(256),
    page_embeddings_model       VARCHAR2(255) NOT NULL,
    page_embeddings_dimension   NUMBER NOT NULL,
    page_embeddings_vector      VECTOR(768, FLOAT32),
    page_embeddings_modality    VARCHAR2(64) DEFAULT 'text' NOT NULL,
    page_embeddings_summary     CLOB DEFAULT '' NOT NULL,
    page_embeddings_updated     TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    page_embeddings_created     TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_page_embeddings_id PRIMARY KEY (page_embeddings_id),
    CONSTRAINT fk_page_embeddings_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_page_embeddings_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_page_embeddings_file_pages FOREIGN KEY (file_pages_id)
        REFERENCES file_pages(file_pages_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE page_embeddings_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_page_embeddings_id
    BEFORE INSERT ON page_embeddings
    FOR EACH ROW
    WHEN (NEW.page_embeddings_id IS NULL)
BEGIN
    :NEW.page_embeddings_id := page_embeddings_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_page_embeddings_updated
BEFORE UPDATE ON page_embeddings
FOR EACH ROW
BEGIN
    :NEW.page_embeddings_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_page_embeddings_file_modality
    ON page_embeddings (file_id, page_embeddings_modality, file_pages_id);
--

CREATE INDEX idx_page_embeddings_user_file
    ON page_embeddings (user_id, file_id);
--

CREATE INDEX idx_page_embeddings_page
    ON page_embeddings (file_pages_id);
--

CREATE INDEX idx_page_embeddings_archive
    ON page_embeddings (user_id, archive_slug, page_embeddings_modality);
--

-- Use neighbor partitions so embeddings remain writable on ADB deployments
-- that still run with COMPATIBLE 23.5 during iterative ingestion.
CREATE VECTOR INDEX idx_page_embeddings_vector
    ON page_embeddings (page_embeddings_vector)
    INCLUDE (user_id, file_id, file_pages_id, archive_slug, page_embeddings_modality)
    ORGANIZATION NEIGHBOR PARTITIONS
    WITH TARGET ACCURACY 95;
--

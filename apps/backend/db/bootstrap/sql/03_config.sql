CREATE TABLE config (
    config_id          NUMBER NOT NULL,
    config_key         VARCHAR2(200) NOT NULL,
    config_value       CLOB,
    config_type        VARCHAR2(50) DEFAULT 'string',
    config_category    VARCHAR2(100),
    config_description VARCHAR2(500),
    config_encrypted   NUMBER DEFAULT 0,
    config_state       NUMBER DEFAULT 1 NOT NULL,
    config_updated     TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    config_created     TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_config_id PRIMARY KEY (config_id),
    CONSTRAINT uk_config_key UNIQUE (config_key)
);
--

CREATE SEQUENCE config_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_config_id
    BEFORE INSERT ON config
    FOR EACH ROW
    WHEN (NEW.config_id IS NULL)
BEGIN
    :NEW.config_id := config_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_config_updated
    BEFORE UPDATE ON config
    FOR EACH ROW
BEGIN
    :NEW.config_updated := SYSDATE;
END;
/
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('wizard.completed', 'false', 'string', 'general', 'Indicates whether the initial setup wizard has been completed');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.max_parallel_jobs', '2', 'number', 'rag', 'Maximum number of ingestion jobs that can run in parallel');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.max_parallel_documents', '3', 'number', 'rag', 'Maximum number of documents processed in parallel across ingestion workers');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.native_text_min_chars', '160', 'number', 'rag', 'Minimum native text length required before using embedded PDF text instead of OCR during ingestion');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.visual_enrichment_enabled', 'false', 'boolean', 'rag', 'Enable OCI multimodal visual enrichment during ingestion');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.page_image_embeddings_enabled', 'true', 'boolean', 'rag', 'Enable page image embeddings for pages with strong visual signals detected during ingestion');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.ingest.structured_facts_enabled', 'false', 'boolean', 'rag', 'Enable OCI structured document-fact extraction during ingestion');
--


INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('app.name', 'AI Document Analyzer', 'string', 'app', 'Display name of the application');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('app.agent_name', 'Nadia Assist', 'string', 'app', 'Display name of the chat agent');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('app.session_timeout_minutes', '480', 'number', 'app', 'Session timeout in minutes used for JWT expiration');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('app.timezone', 'America/Lima', 'string', 'app', 'Default timezone used by the agent runtime');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('app.language', 'es', 'string', 'app', 'Default language used by the agent');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('embedding.dimension', '768', 'number', 'embedding', 'Embedding vector dimension');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('embedding.answer_max_evidence', '3', 'number', 'embedding', 'Maximum evidence chunks used for grounded answers');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('embedding.visual_analysis_top_k', '2', 'number', 'embedding', 'Maximum pages to evaluate with multimodal visual verification');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.doc_shortlist_scoped', '12', 'number', 'rag', 'Default document shortlist size when scope is inferred or manual');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.doc_shortlist_global', '20', 'number', 'rag', 'Default document shortlist size when scope is global');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.page_pool_scoped', '36', 'number', 'rag', 'Default page candidate pool size when scope is inferred or manual');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.page_pool_global', '60', 'number', 'rag', 'Default page candidate pool size when scope is global');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.rerank_scoped', '24', 'number', 'rag', 'Default rerank pool size when scope is inferred or manual');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.rerank_global', '32', 'number', 'rag', 'Default rerank pool size when scope is global');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.max_candidates', '2000', 'number', 'rag', 'Maximum candidate pool size for dense/lexical retrieval before fusion');
--

INSERT INTO config (config_key, config_value, config_type, config_category, config_description)
VALUES ('rag.retrieval.max_mmr_pool', '1200', 'number', 'rag', 'Maximum candidate pool size after MMR diversification');
--
--

CREATE TABLE file_pages (
    file_pages_id               NUMBER NOT NULL,
    user_id                     NUMBER NOT NULL,
    file_id                     NUMBER NOT NULL,
    file_pages_number           NUMBER NOT NULL,
    file_pages_image_path_local VARCHAR2(1024) DEFAULT '' NOT NULL,
    file_pages_output_obj_name  VARCHAR2(1024) DEFAULT 'local-page-only' NOT NULL,
    file_pages_ocr_obj_name     VARCHAR2(1024) DEFAULT '' NOT NULL,
    file_pages_ocr_confidence   NUMBER DEFAULT 0 NOT NULL,
    file_pages_ocr_method       VARCHAR2(64) DEFAULT 'pdf_text' NOT NULL,
    file_pages_ocr_text         CLOB DEFAULT 'No OCR text extracted.' NOT NULL,
    file_pages_markdown_text    CLOB,
    file_pages_visual_summary   CLOB,
    file_pages_layout_json      CLOB DEFAULT '{}' NOT NULL,
    file_pages_search_text      CLOB DEFAULT '' NOT NULL,
    file_pages_visual_flags     VARCHAR2(4000),
    file_pages_text_quality     NUMBER DEFAULT 0 NOT NULL,
    file_pages_width            NUMBER DEFAULT 0 NOT NULL,
    file_pages_height           NUMBER DEFAULT 0 NOT NULL,
    file_pages_state            NUMBER DEFAULT 1 NOT NULL,
    file_pages_updated          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_pages_created          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_pages_id PRIMARY KEY (file_pages_id),
    CONSTRAINT fk_file_pages_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_pages_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE file_pages_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_pages_id
    BEFORE INSERT ON file_pages
    FOR EACH ROW
    WHEN (NEW.file_pages_id IS NULL)
BEGIN
    :NEW.file_pages_id := file_pages_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_pages_updated
BEFORE UPDATE ON file_pages
FOR EACH ROW
BEGIN
    :NEW.file_pages_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_pages_file_number
    ON file_pages (file_id, file_pages_number);
--

CREATE INDEX idx_file_pages_user_quality
    ON file_pages (user_id, file_pages_text_quality);
--

CREATE INDEX idx_file_pages_search_text
    ON file_pages (file_pages_search_text)
    INDEXTYPE IS CTXSYS.CONTEXT
    PARAMETERS ('MAINTENANCE AUTO');
--

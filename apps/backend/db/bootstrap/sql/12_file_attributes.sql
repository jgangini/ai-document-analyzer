CREATE TABLE file_attributes (
    file_attribute_id             NUMBER NOT NULL,
    user_id                       NUMBER NOT NULL,
    file_group_id                 NUMBER,
    file_id                       NUMBER NOT NULL,
    page_id                       NUMBER,
    attribute_key                 VARCHAR2(128) DEFAULT '' NOT NULL,
    attribute_value_text          CLOB,
    attribute_value_number        NUMBER,
    attribute_value_date          DATE,
    attribute_value_bool          NUMBER,
    source_type                   VARCHAR2(64) DEFAULT 'ocr' NOT NULL,
    metadata_json                 CLOB DEFAULT '{}' NOT NULL,
    confidence                    NUMBER,
    file_attribute_updated        TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_attribute_created        TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_attributes_id PRIMARY KEY (file_attribute_id),
    CONSTRAINT fk_file_attributes_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_attributes_group FOREIGN KEY (file_group_id)
        REFERENCES file_groups(file_group_id) ON DELETE SET NULL,
    CONSTRAINT fk_file_attributes_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_attributes_page FOREIGN KEY (page_id)
        REFERENCES file_pages(file_pages_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE file_attributes_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_attributes_id
    BEFORE INSERT ON file_attributes
    FOR EACH ROW
    WHEN (NEW.file_attribute_id IS NULL)
BEGIN
    :NEW.file_attribute_id := file_attributes_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_attributes_updated
BEFORE UPDATE ON file_attributes
FOR EACH ROW
BEGIN
    :NEW.file_attribute_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_attributes_key
    ON file_attributes (user_id, attribute_key);
--

CREATE INDEX idx_file_attributes_group_key
    ON file_attributes (file_group_id, attribute_key);
--

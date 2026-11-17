CREATE TABLE file_links (
    file_link_id                  NUMBER NOT NULL,
    user_id                       NUMBER NOT NULL,
    file_group_id                 NUMBER,
    file_id                       NUMBER NOT NULL,
    page_id                       NUMBER,
    link_type                     VARCHAR2(64) DEFAULT '' NOT NULL,
    source_label                  VARCHAR2(512),
    target_label                  VARCHAR2(512),
    link_key                      VARCHAR2(128),
    metadata_json                 CLOB DEFAULT '{}' NOT NULL,
    confidence                    NUMBER,
    file_link_updated             TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_link_created             TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_links_id PRIMARY KEY (file_link_id),
    CONSTRAINT fk_file_links_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_links_group FOREIGN KEY (file_group_id)
        REFERENCES file_groups(file_group_id) ON DELETE SET NULL,
    CONSTRAINT fk_file_links_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_links_page FOREIGN KEY (page_id)
        REFERENCES file_pages(file_pages_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE file_links_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_links_id
    BEFORE INSERT ON file_links
    FOR EACH ROW
    WHEN (NEW.file_link_id IS NULL)
BEGIN
    :NEW.file_link_id := file_links_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_links_updated
BEFORE UPDATE ON file_links
FOR EACH ROW
BEGIN
    :NEW.file_link_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_links_type
    ON file_links (user_id, link_type);
--

CREATE INDEX idx_file_links_key
    ON file_links (user_id, link_key);
--

CREATE TABLE file_entities (
    file_entity_id                NUMBER NOT NULL,
    user_id                       NUMBER NOT NULL,
    file_group_id                 NUMBER,
    file_id                       NUMBER NOT NULL,
    page_id                       NUMBER,
    entity_role                   VARCHAR2(64) DEFAULT '' NOT NULL,
    entity_type                   VARCHAR2(64) DEFAULT 'organization' NOT NULL,
    entity_name                   VARCHAR2(512),
    person_name                   VARCHAR2(512),
    identifier_value              VARCHAR2(128),
    has_visible_signature         NUMBER DEFAULT 0 NOT NULL,
    bbox_json                     CLOB DEFAULT '{}' NOT NULL,
    metadata_json                 CLOB DEFAULT '{}' NOT NULL,
    confidence                    NUMBER,
    file_entity_updated           TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_entity_created           TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_entities_id PRIMARY KEY (file_entity_id),
    CONSTRAINT fk_file_entities_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_entities_group FOREIGN KEY (file_group_id)
        REFERENCES file_groups(file_group_id) ON DELETE SET NULL,
    CONSTRAINT fk_file_entities_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_entities_page FOREIGN KEY (page_id)
        REFERENCES file_pages(file_pages_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE file_entities_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_entities_id
    BEFORE INSERT ON file_entities
    FOR EACH ROW
    WHEN (NEW.file_entity_id IS NULL)
BEGIN
    :NEW.file_entity_id := file_entities_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_entities_updated
BEFORE UPDATE ON file_entities
FOR EACH ROW
BEGIN
    :NEW.file_entity_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_entities_role
    ON file_entities (user_id, entity_role);
--

CREATE INDEX idx_file_entities_name
    ON file_entities (user_id, entity_name);
--

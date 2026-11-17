CREATE TABLE agent_store_items (
    agent_store_items_id         NUMBER NOT NULL,
    agent_store_namespace        VARCHAR2(200) NOT NULL,
    agent_store_item_key         VARCHAR2(200) NOT NULL,
    agent_store_value_json       CLOB NOT NULL,
    agent_store_updated          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    agent_store_created          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_agent_store_items_id PRIMARY KEY (agent_store_items_id),
    CONSTRAINT uk_agent_store_items_key UNIQUE (agent_store_namespace, agent_store_item_key)
);
--

CREATE SEQUENCE agent_store_items_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_agent_store_items_id
    BEFORE INSERT ON agent_store_items
    FOR EACH ROW
    WHEN (NEW.agent_store_items_id IS NULL)
BEGIN
    :NEW.agent_store_items_id := agent_store_items_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_agent_store_items_updated
BEFORE UPDATE ON agent_store_items
FOR EACH ROW
BEGIN
    :NEW.agent_store_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX agent_store_items_idx1
    ON agent_store_items (agent_store_namespace, agent_store_updated);
--

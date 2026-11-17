CREATE TABLE agent_checkpoints (
    agent_checkpoints_id                 NUMBER NOT NULL,
    agent_threads_thread_id              VARCHAR2(255) NOT NULL,
    agent_checkpoints_namespace          VARCHAR2(255) DEFAULT '' NOT NULL,
    agent_checkpoints_checkpoint_id      VARCHAR2(255) NOT NULL,
    agent_checkpoints_parent_id          VARCHAR2(255),
    agent_checkpoints_config_json        CLOB NOT NULL,
    agent_checkpoints_checkpoint_typed   CLOB NOT NULL,
    agent_checkpoints_metadata_typed     CLOB NOT NULL,
    agent_checkpoints_versions_json      CLOB,
    agent_checkpoints_created            TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_agent_checkpoints_id PRIMARY KEY (agent_checkpoints_id),
    CONSTRAINT uk_agent_checkpoints_key UNIQUE (
        agent_threads_thread_id,
        agent_checkpoints_namespace,
        agent_checkpoints_checkpoint_id
    ),
    CONSTRAINT fk_agent_checkpoints_thread FOREIGN KEY (agent_threads_thread_id)
        REFERENCES agent_threads(agent_threads_thread_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE agent_checkpoints_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_agent_checkpoints_id
    BEFORE INSERT ON agent_checkpoints
    FOR EACH ROW
    WHEN (NEW.agent_checkpoints_id IS NULL)
BEGIN
    :NEW.agent_checkpoints_id := agent_checkpoints_id_seq.NEXTVAL;
END;
/
--

CREATE INDEX agent_checkpoints_idx1
    ON agent_checkpoints (
        agent_threads_thread_id,
        agent_checkpoints_namespace,
        agent_checkpoints_created
    );
--

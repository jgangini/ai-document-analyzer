CREATE TABLE agent_checkpoint_writes (
    agent_checkpoint_writes_id            NUMBER NOT NULL,
    agent_threads_thread_id               VARCHAR2(255) NOT NULL,
    agent_checkpoints_namespace           VARCHAR2(255) DEFAULT '' NOT NULL,
    agent_checkpoints_checkpoint_id       VARCHAR2(255) NOT NULL,
    agent_checkpoint_writes_task_id       VARCHAR2(255) NOT NULL,
    agent_checkpoint_writes_task_path     VARCHAR2(1000),
    agent_checkpoint_writes_write_idx     NUMBER NOT NULL,
    agent_checkpoint_writes_channel_name  VARCHAR2(255) NOT NULL,
    agent_checkpoint_writes_value_typed   CLOB NOT NULL,
    agent_checkpoint_writes_created       TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_agent_checkpoint_writes_id PRIMARY KEY (agent_checkpoint_writes_id)
);
--

CREATE SEQUENCE agent_checkpoint_writes_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_agent_checkpoint_writes_id
    BEFORE INSERT ON agent_checkpoint_writes
    FOR EACH ROW
    WHEN (NEW.agent_checkpoint_writes_id IS NULL)
BEGIN
    :NEW.agent_checkpoint_writes_id := agent_checkpoint_writes_id_seq.NEXTVAL;
END;
/
--

CREATE INDEX agent_checkpoint_writes_idx1
    ON agent_checkpoint_writes (
        agent_threads_thread_id,
        agent_checkpoints_namespace,
        agent_checkpoints_checkpoint_id,
        agent_checkpoint_writes_write_idx
    );
--

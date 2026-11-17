CREATE TABLE agent_threads (
    agent_threads_id         NUMBER NOT NULL,
    agent_threads_thread_id  VARCHAR2(255) NOT NULL,
    agent_threads_updated    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    agent_threads_created    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_agent_threads_id PRIMARY KEY (agent_threads_id),
    CONSTRAINT uk_agent_threads_thread_id UNIQUE (agent_threads_thread_id)
);
--

CREATE SEQUENCE agent_threads_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_agent_threads_id
    BEFORE INSERT ON agent_threads
    FOR EACH ROW
    WHEN (NEW.agent_threads_id IS NULL)
BEGIN
    :NEW.agent_threads_id := agent_threads_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_agent_threads_updated
BEFORE UPDATE ON agent_threads
FOR EACH ROW
BEGIN
    :NEW.agent_threads_updated := CURRENT_TIMESTAMP;
END;
/
--

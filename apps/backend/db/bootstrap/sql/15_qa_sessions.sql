CREATE TABLE qa_sessions (
    qa_sessions_id                     NUMBER NOT NULL,
    user_id                            NUMBER NOT NULL,
    file_id                            NUMBER NULL,
    qa_conversations_id                NUMBER NULL,
    qa_sessions_turn_index             NUMBER DEFAULT 0 NOT NULL,
    qa_sessions_question               CLOB NOT NULL,
    qa_sessions_retrieval_metadata     CLOB DEFAULT '{}' NOT NULL,
    qa_sessions_answer                 CLOB DEFAULT '' NOT NULL,
    qa_sessions_model_used             VARCHAR2(255) DEFAULT '' NOT NULL,
    qa_sessions_state                  NUMBER DEFAULT 1 NOT NULL,
    qa_sessions_updated                TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    qa_sessions_created                TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_qa_sessions_id PRIMARY KEY (qa_sessions_id),
    CONSTRAINT fk_qa_sessions_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_sessions_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_sessions_conversation FOREIGN KEY (qa_conversations_id)
        REFERENCES qa_conversations(qa_conversations_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE qa_sessions_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_sessions_id
    BEFORE INSERT ON qa_sessions
    FOR EACH ROW
    WHEN (NEW.qa_sessions_id IS NULL)
BEGIN
    :NEW.qa_sessions_id := qa_sessions_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_qa_sessions_updated
BEFORE UPDATE ON qa_sessions
FOR EACH ROW
BEGIN
    :NEW.qa_sessions_updated := CURRENT_TIMESTAMP;
END;
/
--

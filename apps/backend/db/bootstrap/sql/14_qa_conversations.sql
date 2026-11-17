CREATE TABLE qa_conversations (
    qa_conversations_id                NUMBER NOT NULL,
    user_id                            NUMBER NOT NULL,
    qa_conversations_title             VARCHAR2(255) DEFAULT 'New chat' NOT NULL,
    qa_conversations_state             NUMBER DEFAULT 1 NOT NULL,
    qa_conversations_updated           TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    qa_conversations_created           TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_qa_conversations_id PRIMARY KEY (qa_conversations_id),
    CONSTRAINT fk_qa_conversations_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE qa_conversations_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_conversations_id
    BEFORE INSERT ON qa_conversations
    FOR EACH ROW
    WHEN (NEW.qa_conversations_id IS NULL)
BEGIN
    :NEW.qa_conversations_id := qa_conversations_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_qa_conversations_updated
BEFORE UPDATE ON qa_conversations
FOR EACH ROW
BEGIN
    :NEW.qa_conversations_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE TABLE qa_trace_runs (
    qa_trace_id                       VARCHAR2(64) NOT NULL,
    qa_trace_thread_id                VARCHAR2(255) NOT NULL,
    user_id                           NUMBER NULL,
    qa_conversations_id               NUMBER NULL,
    qa_trace_question                 CLOB NOT NULL,
    qa_trace_status                   VARCHAR2(32) DEFAULT 'running' NOT NULL,
    qa_trace_answerability_route      VARCHAR2(64) DEFAULT 'pending' NOT NULL,
    qa_trace_answer                   CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_cited_sources_count      NUMBER DEFAULT 0 NOT NULL,
    qa_trace_evidence_sources_count   NUMBER DEFAULT 0 NOT NULL,
    qa_trace_metadata                 CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_error                    CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_started                  TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    qa_trace_finished                 TIMESTAMP(6) NULL,
    CONSTRAINT pk_qa_trace_runs PRIMARY KEY (qa_trace_id),
    CONSTRAINT fk_qa_trace_runs_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_trace_runs_conversation FOREIGN KEY (qa_conversations_id)
        REFERENCES qa_conversations(qa_conversations_id) ON DELETE SET NULL
);
--

CREATE INDEX idx_qa_trace_runs_thread ON qa_trace_runs(qa_trace_thread_id);
--

CREATE TABLE qa_trace_steps (
    qa_trace_step_id                  NUMBER NOT NULL,
    qa_trace_id                       VARCHAR2(64) NOT NULL,
    qa_trace_step_node                VARCHAR2(128) DEFAULT 'graph' NOT NULL,
    qa_trace_step_status              VARCHAR2(32) DEFAULT 'completed' NOT NULL,
    qa_trace_step_payload             CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_step_state_patch         CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_step_duration_ms         NUMBER NULL,
    qa_trace_step_error               CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_trace_step_created             TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_qa_trace_steps PRIMARY KEY (qa_trace_step_id),
    CONSTRAINT fk_qa_trace_steps_run FOREIGN KEY (qa_trace_id)
        REFERENCES qa_trace_runs(qa_trace_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE qa_trace_steps_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_trace_steps_id
    BEFORE INSERT ON qa_trace_steps
    FOR EACH ROW
    WHEN (NEW.qa_trace_step_id IS NULL)
BEGIN
    :NEW.qa_trace_step_id := qa_trace_steps_id_seq.NEXTVAL;
END;
/
--

CREATE INDEX idx_qa_trace_steps_run ON qa_trace_steps(qa_trace_id, qa_trace_step_created);
--

CREATE TABLE qa_eval_cases (
    qa_eval_case_id                   NUMBER NOT NULL,
    qa_eval_case_name                 VARCHAR2(255) NOT NULL,
    qa_eval_case_category             VARCHAR2(64) DEFAULT 'manual' NOT NULL,
    qa_eval_case_question             CLOB NOT NULL,
    qa_eval_case_expected             CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_eval_case_source               VARCHAR2(255) DEFAULT 'manual' NOT NULL,
    qa_eval_case_state                NUMBER DEFAULT 1 NOT NULL,
    qa_eval_case_created              TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_qa_eval_cases PRIMARY KEY (qa_eval_case_id)
);
--

CREATE SEQUENCE qa_eval_cases_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_eval_cases_id
    BEFORE INSERT ON qa_eval_cases
    FOR EACH ROW
    WHEN (NEW.qa_eval_case_id IS NULL)
BEGIN
    :NEW.qa_eval_case_id := qa_eval_cases_id_seq.NEXTVAL;
END;
/
--

CREATE TABLE qa_eval_runs (
    qa_eval_run_id                    NUMBER NOT NULL,
    qa_eval_run_name                  VARCHAR2(255) NOT NULL,
    qa_eval_run_status                VARCHAR2(32) DEFAULT 'running' NOT NULL,
    qa_eval_run_metadata              CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_eval_run_started               TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    qa_eval_run_finished              TIMESTAMP(6) NULL,
    CONSTRAINT pk_qa_eval_runs PRIMARY KEY (qa_eval_run_id)
);
--

CREATE SEQUENCE qa_eval_runs_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_eval_runs_id
    BEFORE INSERT ON qa_eval_runs
    FOR EACH ROW
    WHEN (NEW.qa_eval_run_id IS NULL)
BEGIN
    :NEW.qa_eval_run_id := qa_eval_runs_id_seq.NEXTVAL;
END;
/
--

CREATE TABLE qa_eval_results (
    qa_eval_result_id                 NUMBER NOT NULL,
    qa_eval_run_id                    NUMBER NOT NULL,
    qa_eval_case_id                   NUMBER NOT NULL,
    qa_trace_id                       VARCHAR2(64) NULL,
    qa_eval_result_status             VARCHAR2(32) DEFAULT 'pending' NOT NULL,
    qa_eval_result_score              NUMBER DEFAULT 0 NOT NULL,
    qa_eval_result_details            CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_eval_result_created            TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_qa_eval_results PRIMARY KEY (qa_eval_result_id),
    CONSTRAINT fk_qa_eval_results_run FOREIGN KEY (qa_eval_run_id)
        REFERENCES qa_eval_runs(qa_eval_run_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_eval_results_case FOREIGN KEY (qa_eval_case_id)
        REFERENCES qa_eval_cases(qa_eval_case_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_eval_results_trace FOREIGN KEY (qa_trace_id)
        REFERENCES qa_trace_runs(qa_trace_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE qa_eval_results_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_eval_results_id
    BEFORE INSERT ON qa_eval_results
    FOR EACH ROW
    WHEN (NEW.qa_eval_result_id IS NULL)
BEGIN
    :NEW.qa_eval_result_id := qa_eval_results_id_seq.NEXTVAL;
END;
/
--

CREATE TABLE qa_feedback_events (
    qa_feedback_event_id              NUMBER NOT NULL,
    user_id                           NUMBER NULL,
    qa_conversations_id               NUMBER NULL,
    qa_trace_id                       VARCHAR2(64) NULL,
    qa_feedback_event_type            VARCHAR2(64) DEFAULT 'event' NOT NULL,
    qa_feedback_value                 VARCHAR2(64) DEFAULT 'none' NOT NULL,
    qa_feedback_assistant_message_id  VARCHAR2(128) DEFAULT 'none' NOT NULL,
    qa_feedback_user_prompt           CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_feedback_assistant_answer      CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_feedback_metadata              CLOB DEFAULT EMPTY_CLOB() NOT NULL,
    qa_feedback_created               TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_qa_feedback_events PRIMARY KEY (qa_feedback_event_id),
    CONSTRAINT fk_qa_feedback_events_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_qa_feedback_events_conversation FOREIGN KEY (qa_conversations_id)
        REFERENCES qa_conversations(qa_conversations_id) ON DELETE SET NULL,
    CONSTRAINT fk_qa_feedback_events_trace FOREIGN KEY (qa_trace_id)
        REFERENCES qa_trace_runs(qa_trace_id) ON DELETE SET NULL
);
--

CREATE SEQUENCE qa_feedback_events_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_qa_feedback_events_id
    BEFORE INSERT ON qa_feedback_events
    FOR EACH ROW
    WHEN (NEW.qa_feedback_event_id IS NULL)
BEGIN
    :NEW.qa_feedback_event_id := qa_feedback_events_id_seq.NEXTVAL;
END;
/
--

CREATE INDEX idx_qa_feedback_events_user ON qa_feedback_events(user_id, qa_feedback_created);
--

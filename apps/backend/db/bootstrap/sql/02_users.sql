CREATE TABLE users (
    user_id         NUMBER NOT NULL,
    user_group_id   NUMBER NOT NULL,
    user_username   VARCHAR2(250) NOT NULL,
    user_password   VARCHAR2(500) NOT NULL,
    user_name       VARCHAR2(500) NOT NULL,
    user_last_name  VARCHAR2(500) NOT NULL,
    user_state      NUMBER DEFAULT 1 NOT NULL,
    user_last_login TIMESTAMP(6),
    user_updated    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    user_created    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_user_id PRIMARY KEY (user_id),
    CONSTRAINT fk_users_user_group FOREIGN KEY (user_group_id)
    REFERENCES user_group(user_group_id) ENABLE
);
--

CREATE UNIQUE INDEX user_username_unq ON users (user_username ASC);
--

CREATE SEQUENCE user_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_users_id
    BEFORE INSERT ON users
    FOR EACH ROW
    WHEN (NEW.user_id IS NULL)
BEGIN
    :NEW.user_id := user_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_users_updated
BEFORE UPDATE ON users
FOR EACH ROW
BEGIN
    :NEW.user_updated := CURRENT_TIMESTAMP;
END;
/
--

-- Per-message classification and finding lookups must not scan an account's
-- entire evidence set once for every message.
CREATE INDEX idx_classifications_account_message_type
    ON classifications(account_id, message_db_id, classifier_type);
CREATE INDEX idx_security_account_message
    ON security_findings(account_id, message_db_id);
CREATE INDEX idx_classifications_account_thread_type
    ON classifications(account_id, thread_key, target_type, classifier_type);

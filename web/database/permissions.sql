-- Database Permissions for Minimal Privilege
-- Based on §5.4 Security and Production Requirements

-- 应用账号：最小权限原则
-- 1. 只读权限：大部分表（知识图谱、课程、练习题等）
-- 2. 写入权限：仅学生行为相关表（学习事件、答题记录、问答记录）
-- 3. 禁止：DDL、DELETE、TRUNCATE

-- 假设应用账号名为 app_user，在部署前需创建该账号：
-- CREATE USER app_user WITH PASSWORD 'secure_password_from_env';

-- 撤销默认的public schema权限
REVOKE CREATE ON SCHEMA public FROM app_user;
REVOKE ALL ON DATABASE kglearn FROM app_user;

-- 连接数据库权限
GRANT CONNECT ON DATABASE kglearn TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;

-- 1. 只读权限：知识图谱核心表（由seed_import写入，应用只读）
GRANT SELECT ON TABLE courses TO app_user;
GRANT SELECT ON TABLE knowledge_nodes TO app_user;
GRANT SELECT ON TABLE knowledge_edges TO app_user;
GRANT SELECT ON TABLE exercises TO app_user;
GRANT SELECT ON TABLE exercise_related_nodes TO app_user;

-- 2. 只读权限：导入元数据（运维CLI写入，应用只读）
GRANT SELECT ON TABLE import_runs TO app_user;

-- 3. 读写权限：认证会话表（应用需要创建/查询/删除会话）
GRANT SELECT, INSERT, DELETE ON TABLE users TO app_user;
GRANT SELECT, INSERT, DELETE ON TABLE sessions TO app_user;
GRANT USAGE, SELECT ON SEQUENCE users_id_seq TO app_user;

-- 4. 写入权限：学生行为数据表
-- 学习事件
GRANT SELECT, INSERT ON TABLE learning_events TO app_user;
GRANT USAGE, SELECT ON SEQUENCE learning_events_event_id_seq TO app_user;

-- 答题记录
GRANT SELECT, INSERT ON TABLE exercise_attempts TO app_user;
GRANT USAGE, SELECT ON SEQUENCE exercise_attempts_attempt_id_seq TO app_user;

-- 问答记录
GRANT SELECT, INSERT ON TABLE qa_records TO app_user;
GRANT USAGE, SELECT ON SEQUENCE qa_records_record_id_seq TO app_user;

-- 5. 显式禁止危险操作
-- 禁止UPDATE已提交的答题记录和学习事件（幂等性保证）
-- 禁止DELETE业务数据（保留审计追踪）
-- 禁止ALTER TABLE、DROP TABLE等DDL操作（已通过撤销CREATE权限实现）

-- 注意事项：
-- 1. 生产环境必须使用独立的应用账号，密码通过环境变量注入
-- 2. 迁移和种子导入使用更高权限的管理账号（如postgres或单独的migrate_user）
-- 3. 该权限设置在首次部署后执行，修改表结构时需临时提权或使用管理账号
-- 4. 定期审计 pg_stat_statements 确认应用未尝试执行禁止操作

-- 验证权限设置（使用管理账号执行）：
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.table_privileges
-- WHERE grantee = 'app_user'
-- ORDER BY table_name, privilege_type;

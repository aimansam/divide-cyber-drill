-- OxBlood Database Schema
-- PostgreSQL 15+
-- Comprehensive schema for cybersecurity training platform

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

CREATE TYPE user_role AS ENUM ('student', 'instructor', 'team_leader', 'administrator', 'observer');
CREATE TYPE lab_status AS ENUM ('draft', 'published', 'archived');
CREATE TYPE lab_difficulty AS ENUM ('beginner', 'easy', 'medium', 'hard', 'expert');
CREATE TYPE drill_status AS ENUM ('scheduled', 'active', 'paused', 'completed', 'cancelled');
CREATE TYPE submission_status AS ENUM ('pending', 'correct', 'incorrect', 'partial', 'reviewed');
CREATE TYPE report_status AS ENUM ('draft', 'submitted', 'under_review', 'graded', 'approved');
CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'informational');
CREATE TYPE evidence_type AS ENUM ('screenshot', 'command_output', 'log_excerpt', 'network_capture', 'file', 'other');
CREATE TYPE audit_action AS ENUM ('user.created', 'user.updated', 'user.deleted', 'user.login', 'user.logout', 'lab.created', 'lab.updated', 'lab.published', 'lab.archived', 'drill.created', 'drill.started', 'drill.completed', 'flag.submitted', 'flag.correct', 'flag.incorrect', 'report.created', 'report.submitted', 'report.graded', 'team.created', 'team.updated', 'team.member_added', 'team.member_removed', 'score.updated', 'benchmark.calculated', 'admin.action');
CREATE TYPE notification_type AS ENUM ('info', 'warning', 'error', 'success', 'achievement', 'deadline');
CREATE TYPE learning_path_status AS ENUM ('not_started', 'in_progress', 'completed');

-- ============================================================================
-- MODULE 1: USER MANAGEMENT
-- ============================================================================

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    sub VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    role user_role NOT NULL DEFAULT 'student',
    is_active BOOLEAN NOT NULL DEFAULT true,
    email_verified BOOLEAN NOT NULL DEFAULT false,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT chk_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$')
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_active ON users(is_active) WHERE deleted_at IS NULL;

CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255),
    bio TEXT,
    avatar_url VARCHAR(500),
    organization VARCHAR(255),
    location VARCHAR(255),
    website VARCHAR(500),
    github_username VARCHAR(100),
    linkedin_url VARCHAR(500),
    skills JSONB DEFAULT '[]',
    interests JSONB DEFAULT '[]',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_profiles_user UNIQUE (user_id)
);

CREATE INDEX idx_user_profiles_user ON user_profiles(user_id);

CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    ip_address INET,
    user_agent TEXT,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

CREATE TABLE password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_password_reset_user ON password_reset_tokens(user_id);
CREATE INDEX idx_password_reset_token ON password_reset_tokens(token);
CREATE INDEX idx_password_reset_expires ON password_reset_tokens(expires_at);

CREATE TABLE user_activity_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id INTEGER,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_activity_user ON user_activity_logs(user_id);
CREATE INDEX idx_user_activity_action ON user_activity_logs(action);
CREATE INDEX idx_user_activity_created ON user_activity_logs(created_at);

CREATE TABLE badges (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT NOT NULL,
    icon VARCHAR(50) NOT NULL,
    criteria JSONB NOT NULL,
    category VARCHAR(50) NOT NULL,
    rarity VARCHAR(20) NOT NULL DEFAULT 'common',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE user_badges (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_id INTEGER NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
    earned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_badges UNIQUE (user_id, badge_id)
);

CREATE INDEX idx_user_badges_user ON user_badges(user_id);
CREATE INDEX idx_user_badges_badge ON user_badges(badge_id);

-- ============================================================================
-- MODULE 2: TEAM MANAGEMENT
-- ============================================================================

CREATE TABLE teams (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    organization VARCHAR(255),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_teams_name ON teams(name);
CREATE INDEX idx_teams_active ON teams(is_active) WHERE deleted_at IS NULL;

CREATE TABLE team_memberships (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_team_memberships UNIQUE (team_id, user_id)
);

CREATE INDEX idx_team_memberships_team ON team_memberships(team_id);
CREATE INDEX idx_team_memberships_user ON team_memberships(user_id);

CREATE TABLE team_invitations (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invited_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(255),
    token VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    responded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_team_invitations_team ON team_invitations(team_id);
CREATE INDEX idx_team_invitations_user ON team_invitations(invited_user_id);
CREATE INDEX idx_team_invitations_token ON team_invitations(token);
CREATE INDEX idx_team_invitations_status ON team_invitations(status);

CREATE TABLE team_statistics (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    drill_id INTEGER,
    total_score INTEGER NOT NULL DEFAULT 0,
    flags_captured INTEGER NOT NULL DEFAULT 0,
    objectives_completed INTEGER NOT NULL DEFAULT 0,
    average_time_seconds INTEGER,
    rank_position INTEGER,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_team_statistics_team ON team_statistics(team_id);
CREATE INDEX idx_team_statistics_drill ON team_statistics(drill_id);

-- ============================================================================
-- MODULE 3: LAB MANAGEMENT
-- ============================================================================

CREATE TABLE lab_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    parent_id INTEGER REFERENCES lab_categories(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_categories_parent ON lab_categories(parent_id);

CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    color VARCHAR(7),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE labs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER REFERENCES lab_categories(id) ON DELETE SET NULL,
    difficulty lab_difficulty NOT NULL DEFAULT 'beginner',
    duration_minutes INTEGER,
    status lab_status NOT NULL DEFAULT 'draft',
    is_public BOOLEAN NOT NULL DEFAULT false,
    requires_team BOOLEAN NOT NULL DEFAULT false,
    min_team_size INTEGER,
    max_team_size INTEGER,
    spec JSONB NOT NULL DEFAULT '{}',
    authors JSONB DEFAULT '[]',
    prerequisites JSONB DEFAULT '[]',
    learning_objectives JSONB DEFAULT '[]',
    source_path VARCHAR(500),
    published_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_labs_name ON labs(name);
CREATE INDEX idx_labs_category ON labs(category_id);
CREATE INDEX idx_labs_difficulty ON labs(difficulty);
CREATE INDEX idx_labs_status ON labs(status);
CREATE INDEX idx_labs_public ON labs(is_public);

CREATE TABLE lab_tags (
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lab_id, tag_id)
);

CREATE INDEX idx_lab_tags_lab ON lab_tags(lab_id);
CREATE INDEX idx_lab_tags_tag ON lab_tags(tag_id);

CREATE TABLE target_machines (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,
    os_type VARCHAR(50) NOT NULL,
    os_version VARCHAR(50),
    ip_address INET,
    template_name VARCHAR(100),
    vulnerabilities JSONB DEFAULT '[]',
    services JSONB DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_target_machines_lab ON target_machines(lab_id);

CREATE TABLE lab_objectives (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_required BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_objectives_lab ON lab_objectives(lab_id);

CREATE TABLE lab_flags (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    flag_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    value VARCHAR(255) NOT NULL,
    points INTEGER NOT NULL DEFAULT 100,
    category VARCHAR(50),
    hint TEXT,
    hint_penalty INTEGER NOT NULL DEFAULT 10,
    decay_window_seconds INTEGER NOT NULL DEFAULT 1800,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lab_flags UNIQUE (lab_id, flag_id)
);

CREATE INDEX idx_lab_flags_lab ON lab_flags(lab_id);

CREATE TABLE lab_hints (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    penalty_points INTEGER NOT NULL DEFAULT 5,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_hints_lab ON lab_hints(lab_id);
CREATE INDEX idx_lab_hints_objective ON lab_hints(objective_id);

CREATE TABLE lab_files (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    is_downloadable BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_files_lab ON lab_files(lab_id);

-- ============================================================================
-- MODULE 4: CYBER DRILL MANAGEMENT
-- ============================================================================

CREATE TABLE drills (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    lab_id INTEGER REFERENCES labs(id) ON DELETE SET NULL,
    status drill_status NOT NULL DEFAULT 'scheduled',
    drill_type VARCHAR(50) NOT NULL DEFAULT 'individual',
    scheduled_start_at TIMESTAMP WITH TIME ZONE,
    scheduled_end_at TIMESTAMP WITH TIME ZONE,
    actual_start_at TIMESTAMP WITH TIME ZONE,
    actual_end_at TIMESTAMP WITH TIME ZONE,
    duration_limit_minutes INTEGER,
    max_participants INTEGER,
    rules JSONB DEFAULT '{}',
    environment_config JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_drills_status ON drills(status);
CREATE INDEX idx_drills_lab ON drills(lab_id);
CREATE INDEX idx_drills_scheduled ON drills(scheduled_start_at);

CREATE TABLE drill_scenarios (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    scenario_config JSONB DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_drill_scenarios UNIQUE (drill_id, lab_id)
);

CREATE INDEX idx_drill_scenarios_drill ON drill_scenarios(drill_id);
CREATE INDEX idx_drill_scenarios_lab ON drill_scenarios(lab_id);

CREATE TABLE drill_participants (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'participant',
    status VARCHAR(20) NOT NULL DEFAULT 'registered',
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_drill_participants UNIQUE (drill_id, user_id)
);

CREATE INDEX idx_drill_participants_drill ON drill_participants(drill_id);
CREATE INDEX idx_drill_participants_user ON drill_participants(user_id);
CREATE INDEX idx_drill_participants_team ON drill_participants(team_id);

CREATE TABLE drill_teams (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    team_side VARCHAR(20),
    registered_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_drill_teams UNIQUE (drill_id, team_id)
);

CREATE INDEX idx_drill_teams_drill ON drill_teams(drill_id);
CREATE INDEX idx_drill_teams_team ON drill_teams(team_id);

CREATE TABLE drill_objectives (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    side VARCHAR(20),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drill_objectives_drill ON drill_objectives(drill_id);

CREATE TABLE drill_announcements (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    published_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drill_announcements_drill ON drill_announcements(drill_id);
CREATE INDEX idx_drill_announcements_published ON drill_announcements(published_at);

-- ============================================================================
-- MODULE 5: SUBMISSION SYSTEM
-- ============================================================================

CREATE TABLE submissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER REFERENCES labs(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    submission_type VARCHAR(50) NOT NULL,
    status submission_status NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    review_notes TEXT
);

CREATE INDEX idx_submissions_user ON submissions(user_id);
CREATE INDEX idx_submissions_drill ON submissions(drill_id);
CREATE INDEX idx_submissions_lab ON submissions(lab_id);
CREATE INDEX idx_submissions_team ON submissions(team_id);
CREATE INDEX idx_submissions_status ON submissions(status);
CREATE INDEX idx_submissions_type ON submissions(submission_type);

CREATE TABLE flag_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    flag_value VARCHAR(255) NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT false,
    points_earned INTEGER NOT NULL DEFAULT 0,
    time_decay_factor DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    hints_used INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_flag_submissions UNIQUE (submission_id, lab_flag_id)
);

CREATE INDEX idx_flag_submissions_flag ON flag_submissions(lab_flag_id);
CREATE INDEX idx_flag_submissions_correct ON flag_submissions(is_correct);

CREATE TABLE evidence_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE SET NULL,
    evidence_type evidence_type NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    description TEXT,
    captured_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_evidence_submissions_objective ON evidence_submissions(objective_id);
CREATE INDEX idx_evidence_submissions_type ON evidence_submissions(evidence_type);

CREATE TABLE report_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    file_path VARCHAR(500),
    word_count INTEGER,
    quality_score DECIMAL(5,2),
    grade VARCHAR(10)
);

CREATE INDEX idx_report_submissions_quality ON report_submissions(quality_score);

CREATE TABLE submission_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    flag_value VARCHAR(255) NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT false,
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ip_address INET,
    CONSTRAINT uq_submission_attempts UNIQUE (user_id, lab_flag_id, attempt_number)
);

CREATE INDEX idx_submission_attempts_user ON submission_attempts(user_id);
CREATE INDEX idx_submission_attempts_flag ON submission_attempts(lab_flag_id);
CREATE INDEX idx_submission_attempts_submitted ON submission_attempts(submitted_at);

-- ============================================================================
-- MODULE 6: SCORING SYSTEM
-- ============================================================================

CREATE TABLE scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    total_points INTEGER NOT NULL DEFAULT 0,
    flags_captured INTEGER NOT NULL DEFAULT 0,
    objectives_completed INTEGER NOT NULL DEFAULT 0,
    hints_used INTEGER NOT NULL DEFAULT 0,
    penalty_points INTEGER NOT NULL DEFAULT 0,
    time_bonus_points INTEGER NOT NULL DEFAULT 0,
    first_blood_bonus INTEGER NOT NULL DEFAULT 0,
    completion_time_seconds INTEGER,
    rank_position INTEGER,
    last_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_scores_user_drill UNIQUE (user_id, drill_id),
    CONSTRAINT uq_scores_team_drill UNIQUE (team_id, drill_id)
);

CREATE INDEX idx_scores_user ON scores(user_id);
CREATE INDEX idx_scores_drill ON scores(drill_id);
CREATE INDEX idx_scores_team ON scores(team_id);
CREATE INDEX idx_scores_rank ON scores(rank_position);

CREATE TABLE score_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,
    points_change INTEGER NOT NULL,
    previous_total INTEGER NOT NULL,
    new_total INTEGER NOT NULL,
    details JSONB DEFAULT '{}',
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_score_history_user ON score_history(user_id);
CREATE INDEX idx_score_history_drill ON score_history(drill_id);
CREATE INDEX idx_score_history_team ON score_history(team_id);
CREATE INDEX idx_score_history_recorded ON score_history(recorded_at);

CREATE TABLE first_bloods (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_first_bloods UNIQUE (drill_id, lab_flag_id)
);

CREATE INDEX idx_first_bloods_drill ON first_bloods(drill_id);
CREATE INDEX idx_first_bloods_user ON first_bloods(user_id);

-- ============================================================================
-- MODULE 7: BENCHMARKING SYSTEM
-- ============================================================================

CREATE TABLE benchmarks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    overall_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    offensive_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    defensive_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    web_exploitation_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    network_exploitation_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    active_directory_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    linux_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    windows_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    forensics_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    reporting_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    total_drills_completed INTEGER NOT NULL DEFAULT 0,
    total_flags_captured INTEGER NOT NULL DEFAULT 0,
    average_completion_time_seconds INTEGER,
    last_calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_benchmarks_user UNIQUE (user_id)
);

CREATE INDEX idx_benchmarks_user ON benchmarks(user_id);
CREATE INDEX idx_benchmarks_overall ON benchmarks(overall_score);

CREATE TABLE benchmark_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE SET NULL,
    overall_score DECIMAL(5,2) NOT NULL,
    offensive_score DECIMAL(5,2) NOT NULL,
    defensive_score DECIMAL(5,2) NOT NULL,
    web_exploitation_score DECIMAL(5,2) NOT NULL,
    network_exploitation_score DECIMAL(5,2) NOT NULL,
    active_directory_score DECIMAL(5,2) NOT NULL,
    linux_score DECIMAL(5,2) NOT NULL,
    windows_score DECIMAL(5,2) NOT NULL,
    forensics_score DECIMAL(5,2) NOT NULL,
    reporting_score DECIMAL(5,2) NOT NULL,
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_benchmark_history_user ON benchmark_history(user_id);
CREATE INDEX idx_benchmark_history_drill ON benchmark_history(drill_id);
CREATE INDEX idx_benchmark_history_calculated ON benchmark_history(calculated_at);

-- ============================================================================
-- MODULE 8: REPORTING SYSTEM
-- ============================================================================

CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    status report_status NOT NULL DEFAULT 'draft',
    report_type VARCHAR(50) NOT NULL DEFAULT 'after_action',
    quality_score DECIMAL(5,2),
    grade VARCHAR(10),
    word_count INTEGER,
    file_path VARCHAR(500),
    submitted_at TIMESTAMP WITH TIME ZONE,
    graded_at TIMESTAMP WITH TIME ZONE,
    graded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    instructor_feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reports_drill ON reports(drill_id);
CREATE INDEX idx_reports_user ON reports(user_id);
CREATE INDEX idx_reports_team ON reports(team_id);
CREATE INDEX idx_reports_status ON reports(status);
CREATE INDEX idx_reports_quality ON reports(quality_score);

CREATE TABLE report_findings (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    severity severity_level NOT NULL,
    category VARCHAR(50),
    evidence TEXT,
    impact TEXT,
    recommendation TEXT,
    cvss_score DECIMAL(3,1),
    cwe_id VARCHAR(20),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_report_findings_report ON report_findings(report_id);
CREATE INDEX idx_report_findings_severity ON report_findings(severity);

CREATE TABLE evidence (
    id SERIAL PRIMARY KEY,
    finding_id INTEGER NOT NULL REFERENCES report_findings(id) ON DELETE CASCADE,
    evidence_type evidence_type NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    description TEXT,
    captured_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evidence_finding ON evidence(finding_id);
CREATE INDEX idx_evidence_type ON evidence(evidence_type);

-- ============================================================================
-- MODULE 9: LEARNING PATH SYSTEM
-- ============================================================================

CREATE TABLE learning_paths (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    difficulty lab_difficulty NOT NULL DEFAULT 'beginner',
    estimated_duration_hours INTEGER,
    is_public BOOLEAN NOT NULL DEFAULT true,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_learning_paths_name ON learning_paths(name);
CREATE INDEX idx_learning_paths_difficulty ON learning_paths(difficulty);

CREATE TABLE learning_path_modules (
    id SERIAL PRIMARY KEY,
    learning_path_id INTEGER NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_learning_path_modules_path ON learning_path_modules(learning_path_id);

CREATE TABLE learning_path_labs (
    id SERIAL PRIMARY KEY,
    module_id INTEGER NOT NULL REFERENCES learning_path_modules(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    is_required BOOLEAN NOT NULL DEFAULT true,
    min_score INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_learning_path_labs UNIQUE (module_id, lab_id)
);

CREATE INDEX idx_learning_path_labs_module ON learning_path_labs(module_id);
CREATE INDEX idx_learning_path_labs_lab ON learning_path_labs(lab_id);

CREATE TABLE user_learning_progress (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    learning_path_id INTEGER NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES learning_path_modules(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    status learning_path_status NOT NULL DEFAULT 'not_started',
    score INTEGER,
    completed_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_learning_progress UNIQUE (user_id, learning_path_id, module_id, lab_id)
);

CREATE INDEX idx_user_learning_progress_user ON user_learning_progress(user_id);
CREATE INDEX idx_user_learning_progress_path ON user_learning_progress(learning_path_id);
CREATE INDEX idx_user_learning_progress_status ON user_learning_progress(status);

CREATE TABLE lab_skills (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50) NOT NULL,
    proficiency_level VARCHAR(20) NOT NULL DEFAULT 'intermediate',
    CONSTRAINT uq_lab_skills UNIQUE (lab_id, skill_name)
);

CREATE INDEX idx_lab_skills_lab ON lab_skills(lab_id);
CREATE INDEX idx_lab_skills_category ON lab_skills(skill_category);

-- ============================================================================
-- MODULE 10: ADMIN AND AUDIT SYSTEM
-- ============================================================================

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    action audit_action NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_username VARCHAR(100),
    resource_type VARCHAR(50),
    resource_id INTEGER,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_actor ON audit_logs(actor_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);

CREATE TABLE system_notifications (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    notification_type notification_type NOT NULL DEFAULT 'info',
    target_audience VARCHAR(50) NOT NULL DEFAULT 'all',
    is_active BOOLEAN NOT NULL DEFAULT true,
    starts_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_system_notifications_type ON system_notifications(notification_type);
CREATE INDEX idx_system_notifications_active ON system_notifications(is_active);
CREATE INDEX idx_system_notifications_expires ON system_notifications(expires_at);

CREATE TABLE user_notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_id INTEGER NOT NULL REFERENCES system_notifications(id) ON DELETE CASCADE,
    is_read BOOLEAN NOT NULL DEFAULT false,
    read_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_notifications UNIQUE (user_id, notification_id)
);

CREATE INDEX idx_user_notifications_user ON user_notifications(user_id);
CREATE INDEX idx_user_notifications_read ON user_notifications(is_read);

CREATE TABLE platform_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value JSONB NOT NULL,
    description TEXT,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_platform_settings_key ON platform_settings(setting_key);

CREATE TABLE lab_environment_logs (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER REFERENCES labs(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    resource_name VARCHAR(100) NOT NULL,
    details JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_environment_logs_drill ON lab_environment_logs(drill_id);
CREATE INDEX idx_lab_environment_logs_lab ON lab_environment_logs(lab_id);
CREATE INDEX idx_lab_environment_logs_event ON lab_environment_logs(event_type);
CREATE INDEX idx_lab_environment_logs_created ON lab_environment_logs(created_at);

CREATE TABLE security_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    severity severity_level NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    is_resolved BOOLEAN NOT NULL DEFAULT false,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolution_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_security_events_type ON security_events(event_type);
CREATE INDEX idx_security_events_severity ON security_events(severity);
CREATE INDEX idx_security_events_user ON security_events(user_id);
CREATE INDEX idx_security_events_resolved ON security_events(is_resolved);
CREATE INDEX idx_security_events_created ON security_events(created_at);

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_teams_updated_at BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_labs_updated_at BEFORE UPDATE ON labs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_drills_updated_at BEFORE UPDATE ON drills
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_reports_updated_at BEFORE UPDATE ON reports
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_learning_paths_updated_at BEFORE UPDATE ON learning_paths
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_platform_settings_updated_at BEFORE UPDATE ON platform_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

CREATE VIEW leaderboard AS
SELECT 
    u.id AS user_id,
    u.username,
    u.role,
    COALESCE(SUM(s.total_points), 0) AS total_points,
    COALESCE(SUM(s.flags_captured), 0) AS total_flags,
    COUNT(DISTINCT s.drill_id) AS drills_completed,
    b.overall_score AS benchmark_score
FROM users u
LEFT JOIN scores s ON u.id = s.user_id
LEFT JOIN benchmarks b ON u.id = b.user_id
WHERE u.is_active = true AND u.deleted_at IS NULL
GROUP BY u.id, u.username, u.role, b.overall_score
ORDER BY total_points DESC;

CREATE VIEW active_drills AS
SELECT 
    d.*,
    l.title AS lab_title,
    COUNT(DISTINCT dp.user_id) AS participant_count,
    COUNT(DISTINCT dt.team_id) AS team_count
FROM drills d
LEFT JOIN labs l ON d.lab_id = l.id
LEFT JOIN drill_participants dp ON d.id = dp.drill_id
LEFT JOIN drill_teams dt ON d.id = dt.drill_id
WHERE d.status = 'active' AND d.deleted_at IS NULL
GROUP BY d.id, l.title;

CREATE VIEW user_statistics AS
SELECT 
    u.id AS user_id,
    u.username,
    u.email,
    u.role,
    COUNT(DISTINCT s.drill_id) AS drills_participated,
    COALESCE(SUM(s.total_points), 0) AS total_points,
    COALESCE(SUM(s.flags_captured), 0) AS total_flags,
    b.overall_score,
    b.offensive_score,
    b.defensive_score,
    COUNT(DISTINCT ulp.learning_path_id) AS learning_paths_started,
    COUNT(DISTINCT CASE WHEN ulp.status = 'completed' THEN ulp.id END) AS learning_paths_completed
FROM users u
LEFT JOIN scores s ON u.id = s.user_id
LEFT JOIN benchmarks b ON u.id = b.user_id
LEFT JOIN user_learning_progress ulp ON u.id = ulp.user_id
WHERE u.is_active = true AND u.deleted_at IS NULL
GROUP BY u.id, u.username, u.email, u.role, b.overall_score, b.offensive_score, b.defensive_score;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE users IS 'Main user accounts table';
COMMENT ON TABLE labs IS 'Training labs and scenarios';
COMMENT ON TABLE drills IS 'Cyber drill exercise instances';
COMMENT ON TABLE teams IS 'User teams for collaborative exercises';
COMMENT ON TABLE scores IS 'Current scores for users/teams in drills';
COMMENT ON TABLE benchmarks IS 'Skill benchmark scores for users';
COMMENT ON TABLE reports IS 'After-action reports and assessments';
COMMENT ON TABLE audit_logs IS 'System audit trail for all actions';

-- End of schema

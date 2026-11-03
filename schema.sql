-- Hospital Patient Data Analysis System - MySQL schema
-- Import manually with:  mysql -u root -p < schema.sql
-- (python seed.py also creates everything automatically)

CREATE DATABASE IF NOT EXISTS hospital_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hospital_analytics;

CREATE TABLE IF NOT EXISTS users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    full_name      VARCHAR(100) NOT NULL,
    email          VARCHAR(190) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    role           ENUM('user','admin') NOT NULL DEFAULT 'user',
    is_active      TINYINT(1) NOT NULL DEFAULT 1,
    created_at     DATETIME NOT NULL,
    last_login     DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS departments (
    department_id    INT AUTO_INCREMENT PRIMARY KEY,
    department_name  VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- De-identified: only an age band and an optional gender value are stored
CREATE TABLE IF NOT EXISTS patients (
    patient_id  INT AUTO_INCREMENT PRIMARY KEY,
    age_band    VARCHAR(10) NOT NULL,
    gender      VARCHAR(10) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS visits (
    visit_id       INT AUTO_INCREMENT PRIMARY KEY,
    patient_id     INT NOT NULL,
    department_id  INT NOT NULL,
    visit_date     DATE NOT NULL,
    visit_type     VARCHAR(20) NOT NULL,
    CONSTRAINT fk_visits_patient FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
    CONSTRAINT fk_visits_department FOREIGN KEY (department_id) REFERENCES departments(department_id),
    INDEX idx_visits_date (visit_date),
    INDEX idx_visits_department (department_id),
    INDEX idx_visits_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_log (
    log_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NULL,
    action      VARCHAR(60) NOT NULL,
    detail      VARCHAR(255) NULL,
    ip_address  VARCHAR(45) NULL,
    created_at  DATETIME NOT NULL,
    INDEX idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

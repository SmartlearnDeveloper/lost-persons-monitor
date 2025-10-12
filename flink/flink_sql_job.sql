-- #############################################################################
-- # 1. Definir la tabla de origen (Kafka) con el esquema anidado correcto
-- #############################################################################
CREATE TABLE persons_lost_stream (
    `payload` ROW<
        `before` ROW<person_id INT, first_name STRING, last_name STRING, gender STRING, birth_date INT, age INT, lost_timestamp BIGINT, lost_location STRING, details STRING, status STRING>,
        `after` ROW<person_id INT, first_name STRING, last_name STRING, gender STRING, birth_date INT, age INT, lost_timestamp BIGINT, lost_location STRING, details STRING, status STRING>,
        `op` STRING
    >
) WITH (
    'connector' = 'kafka',
    'topic' = 'lost_persons_server.lost_persons_db.persons_lost',
    'properties.bootstrap.servers' = 'kafka:29092',
    'properties.group.id' = 'flink-group',
    'format' = 'json',
    'scan.startup.mode' = 'earliest-offset'
);

-- #############################################################################
-- # 2. Definir las tablas de destino (MySQL Sinks)
-- #############################################################################
CREATE TABLE agg_age_group_sink (
    age_group STRING PRIMARY KEY NOT ENFORCED,
    `count` BIGINT
) WITH (
    'connector' = 'jdbc',
    'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',
    'table-name' = 'agg_age_group',
    'username' = 'user',
    'password' = 'password'
);

CREATE TABLE agg_gender_sink (
    gender STRING PRIMARY KEY NOT ENFORCED,
    `count` BIGINT
) WITH (
    'connector' = 'jdbc',
    'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',
    'table-name' = 'agg_gender',
    'username' = 'user',
    'password' = 'password'
);

CREATE TABLE agg_hourly_sink (
    hour_of_day INT PRIMARY KEY NOT ENFORCED,
    `count` BIGINT
) WITH (
    'connector' = 'jdbc',
    'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',
    'table-name' = 'agg_hourly',
    'username' = 'user',
    'password' = 'password'
);

-- #############################################################################
-- # 3. Definir y ejecutar las consultas de agregación
-- #############################################################################

-- Consulta para agregación por grupo de edad
INSERT INTO agg_age_group_sink
SELECT
    CASE
        WHEN payload.after.age <= 12 THEN '0-12'
        WHEN payload.after.age <= 18 THEN '13-18'
        WHEN payload.after.age <= 30 THEN '19-30'
        WHEN payload.after.age <= 60 THEN '31-60'
        ELSE '61+'
    END AS age_group,
    COUNT(*) AS `count`
FROM persons_lost_stream
WHERE payload.op = 'c' -- Solo contar inserciones (creates)
GROUP BY
    CASE
        WHEN payload.after.age <= 12 THEN '0-12'
        WHEN payload.after.age <= 18 THEN '13-18'
        WHEN payload.after.age <= 30 THEN '19-30'
        WHEN payload.after.age <= 60 THEN '31-60'
        ELSE '61+'
    END;

-- Consulta para agregación por género
INSERT INTO agg_gender_sink
SELECT
    payload.after.gender AS gender,
    COUNT(*) AS `count`
FROM persons_lost_stream
WHERE payload.op = 'c'
GROUP BY payload.after.gender;

-- Consulta para agregación por hora (con CAST a INT)
INSERT INTO agg_hourly_sink
SELECT
    CAST(HOUR(TO_TIMESTAMP_LTZ(payload.after.lost_timestamp / 1000, 3)) AS INT) AS hour_of_day,
    COUNT(*) as `count`
FROM persons_lost_stream
WHERE payload.op = 'c'
GROUP BY
    CAST(HOUR(TO_TIMESTAMP_LTZ(payload.after.lost_timestamp / 1000, 3)) AS INT);

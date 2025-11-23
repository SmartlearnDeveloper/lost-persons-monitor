package com.lostpersons.flink;

import java.time.DateTimeException;
import java.time.ZoneId;
import org.apache.flink.table.api.EnvironmentSettings;
import org.apache.flink.table.api.StatementSet;
import org.apache.flink.table.api.TableEnvironment;

public final class LostPersonsJob {

    public static void main(String[] args) {
        EnvironmentSettings settings = EnvironmentSettings.newInstance()
                .inStreamingMode()
                .build();
        TableEnvironment tableEnv = TableEnvironment.create(settings);
        tableEnv.getConfig().set("pipeline.name", "Lost Persons Aggregations");
        tableEnv.getConfig().getConfiguration().setString("restart-strategy", "fixed-delay");
        tableEnv.getConfig().getConfiguration().setString("restart-strategy.fixed-delay.attempts", "10");
        tableEnv.getConfig().getConfiguration().setString("restart-strategy.fixed-delay.delay", "10 s");
        configureLocalTimeZone(tableEnv);

        createTables(tableEnv);
        submitInserts(tableEnv);
    }

    private static void configureLocalTimeZone(TableEnvironment tableEnv) {
        String zoneId = System.getenv().getOrDefault("FLINK_LOCAL_TIMEZONE", "UTC");
        try {
            tableEnv.getConfig().setLocalTimeZone(ZoneId.of(zoneId));
        } catch (DateTimeException ex) {
            tableEnv.getConfig().setLocalTimeZone(ZoneId.of("UTC"));
        }
    }

    private static void createTables(TableEnvironment tableEnv) {
        tableEnv.executeSql(
                "CREATE TABLE IF NOT EXISTS persons_lost_stream ("
                        + " payload ROW<"
                        + "   before ROW<person_id INT, first_name STRING, last_name STRING, gender STRING, birth_date INT, age INT, lost_timestamp BIGINT, lost_location STRING, details STRING, status STRING>,"
                        + "   after ROW<person_id INT, first_name STRING, last_name STRING, gender STRING, birth_date INT, age INT, lost_timestamp BIGINT, lost_location STRING, details STRING, status STRING>,"
                        + "   op STRING"
                        + " >"
                        + ") WITH ("
                        + " 'connector' = 'kafka',"
                        + " 'topic' = 'lost_persons_server.lost_persons_db.persons_lost',"
                        + " 'properties.bootstrap.servers' = 'kafka:9092',"
                        + " 'properties.group.id' = 'flink-group',"
                        + " 'properties.allow.auto.create.topics' = 'true',"
                        + " 'format' = 'json',"
                        + " 'scan.startup.mode' = 'earliest-offset'"
                        + ")"
        );

        tableEnv.executeSql(
                "CREATE TABLE IF NOT EXISTS agg_age_group_sink ("
                        + " age_group STRING PRIMARY KEY NOT ENFORCED,"
                        + " `count` BIGINT"
                        + ") WITH ("
                        + " 'connector' = 'jdbc',"
                        + " 'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',"
                        + " 'table-name' = 'agg_age_group',"
                        + " 'username' = 'user',"
                        + " 'password' = 'password'"
                        + ")"
        );

        tableEnv.executeSql(
                "CREATE TABLE IF NOT EXISTS agg_gender_sink ("
                        + " gender STRING PRIMARY KEY NOT ENFORCED,"
                        + " `count` BIGINT"
                        + ") WITH ("
                        + " 'connector' = 'jdbc',"
                        + " 'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',"
                        + " 'table-name' = 'agg_gender',"
                        + " 'username' = 'user',"
                        + " 'password' = 'password'"
                        + ")"
        );

        tableEnv.executeSql(
                "CREATE TABLE IF NOT EXISTS agg_hourly_sink ("
                        + " hour_of_day INT PRIMARY KEY NOT ENFORCED,"
                        + " `count` BIGINT"
                        + ") WITH ("
                        + " 'connector' = 'jdbc',"
                        + " 'url' = 'jdbc:mysql://mysql:3306/lost_persons_db',"
                        + " 'table-name' = 'agg_hourly',"
                        + " 'username' = 'user',"
                        + " 'password' = 'password'"
                        + ")"
        );
    }

    private static void submitInserts(TableEnvironment tableEnv) {
        StatementSet statements = tableEnv.createStatementSet();

        statements.addInsertSql(
                "INSERT INTO agg_age_group_sink "
                        + "SELECT "
                        + " CASE "
                        + "   WHEN payload.after.age <= 12 THEN '0-12' "
                        + "   WHEN payload.after.age <= 18 THEN '13-18' "
                        + "   WHEN payload.after.age <= 30 THEN '19-30' "
                        + "   WHEN payload.after.age <= 60 THEN '31-60' "
                        + "   ELSE '61+' "
                        + " END AS age_group, "
                        + " COUNT(*) AS `count` "
                        + "FROM persons_lost_stream "
                        + "WHERE payload.op = 'c' "
                        + "GROUP BY "
                        + " CASE "
                        + "   WHEN payload.after.age <= 12 THEN '0-12' "
                        + "   WHEN payload.after.age <= 18 THEN '13-18' "
                        + "   WHEN payload.after.age <= 30 THEN '19-30' "
                        + "   WHEN payload.after.age <= 60 THEN '31-60' "
                        + "   ELSE '61+' "
                        + " END"
        );

        statements.addInsertSql(
                "INSERT INTO agg_gender_sink "
                        + "SELECT payload.after.gender AS gender, COUNT(*) AS `count` "
                        + "FROM persons_lost_stream "
                        + "WHERE payload.op = 'c' "
                        + "GROUP BY payload.after.gender"
        );

        statements.addInsertSql(
                "INSERT INTO agg_hourly_sink "
                        + "SELECT "
                        + " CAST(HOUR(TO_TIMESTAMP_LTZ(payload.after.lost_timestamp / 1000, 3)) AS INT) AS hour_of_day, "
                        + " COUNT(*) AS `count` "
                        + "FROM persons_lost_stream "
                        + "WHERE payload.op = 'c' "
                        + "GROUP BY CAST(HOUR(TO_TIMESTAMP_LTZ(payload.after.lost_timestamp / 1000, 3)) AS INT)"
        );

        statements.execute();
    }
}

# Usamos la imagen oficial de Flink como base
FROM apache/flink:1.16.0-scala_2.12-java11

RUN apt-get update && apt-get install -y --no-install-recommends python3-pip netcat && \
    pip3 install kafka-python && \
    rm -rf /var/lib/apt/lists/*

# Copiar conectores y dependencias necesarios
COPY flink/jars/* /opt/flink/lib/
# Driver JDBC adicional si aplica
COPY flink/mysql-connector-j-8.4.0.jar /opt/flink/lib/

# Copiar el job compilado y script de arranque
COPY flink-job/target/lost-persons-job.jar /opt/flink/usrlib/lost-persons-job.jar
COPY flink/start_jobmanager_with_sql.sh /opt/flink/bin/start_jobmanager_with_sql.sh
RUN chmod +x /opt/flink/bin/start_jobmanager_with_sql.sh

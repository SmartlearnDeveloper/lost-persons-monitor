# Usamos la imagen oficial de Flink como base
FROM apache/flink:1.16.0-scala_2.12-java11

# Copiamos todos los conectores .jar de nuestra carpeta local 'jars'
# a la carpeta de librerías de Flink dentro del contenedor.
# Docker se encargará de añadir estos archivos sin borrar los existentes.
COPY jars/* /opt/flink/lib/

# db.py
import datetime
import glob
import logging
import mysql.connector
import os
import pandas as pd

from datetime import datetime
from dotenv import find_dotenv
from dotenv import load_dotenv

# check if environment file exists, else load from os i.e. docker
if os.path.isfile(".env"):
    env_file = find_dotenv(".env")
    load_dotenv(env_file)

# get configuration from environment
DB_HOST=os.environ['DB_HOST']
DB_USERNAME=os.environ['DB_USERNAME']
DB_PASSWORD=os.environ['DB_PASSWORD']
DB_DATABASE=os.environ['DB_DATABASE']
DB_PORT=os.environ['DB_PORT']

def connect_db():
    logging.info("Connecting to the database...")
    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USERNAME,
        password=DB_PASSWORD,
        database=DB_DATABASE,
        port=DB_PORT,
        allow_local_infile=True  # Enable local infile loading
    )
    logging.info("Database connection established.")
    return conn

def close_db(conn):
    logging.info("Closing the database...")
    conn.close
    logging.info("Database connection closed.")

def insert_data(conn, result):
    logging.info("Insert Data Started")
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    mySql_insert_query = "INSERT INTO quicmap (endpoint, port, ALPN, server_versions, timestamp) VALUES (%s, %s, %s, %s, %s)"
    cursor = conn.cursor()

    for ALPN in result['ALPN']:
        for server_versions in result['server_versions']:
            data = (result['endpoint'], result['port'], ALPN, server_versions, timestamp)
            cursor.execute(mySql_insert_query, data)

    conn.commit()
    logging.info(cursor.rowcount, "Record inserted successfully into quicmap table")
    logging.info("Insert Data Ended")

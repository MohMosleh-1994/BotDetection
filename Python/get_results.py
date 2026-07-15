from pathlib import Path

import pandas as pd
import pyodbc

from Config.db_config import (
    SERVER,
    DATABASE,
    USERNAME,
    PASSWORD,
    DRIVER,
)


def load_sql_query(sql_file: Path) -> str:
    with open(sql_file, "r", encoding="utf-8-sig") as file:
        return file.read()


def main():

    sql_path = Path("SQL/GetResults.sql")

    query = load_sql_query(sql_path)

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
        "TrustServerCertificate=yes;"
    )

    print("Connecting to SQL Server...")

    with pyodbc.connect(connection_string) as connection:

        dataframe = pd.read_sql_query(query, connection)

    output_folder = Path("Data/Raw")
    output_folder.mkdir(parents=True, exist_ok=True)

    output_file = output_folder / "Results.csv"

    dataframe.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Saved {len(dataframe)} rows.")
    print(output_file)


if __name__ == "__main__":
    main()
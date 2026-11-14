import pandas as pd

def check_data_quality(df):
    report = {}

    # 1. Unicité
    report['Uniqueness_Errors'] = int(df['ID'].duplicated().sum())

    # 2. Complétude critique
    critical_cols = ['ID', 'Start_Time', 'Start_Lat', 'Start_Lng']
    report['Missing_Critical'] = df[critical_cols].isnull().sum().to_dict()

    # 3. Cohérence des dates
    df_dates = pd.to_datetime(df['Start_Time'], errors='coerce')
    df_end = pd.to_datetime(df['End_Time'], errors='coerce')
    report['Inconsistent_Dates'] = int((df_end < df_dates).sum())

    return report
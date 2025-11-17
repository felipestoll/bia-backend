# ml_engine.py
import pandas as pd
from scipy import stats
import numpy as np
from typing import List, Dict

class MLEngine:
    """
    Motor de Machine Learning (v0.1) para análise de dados vitais.
    Implementa regressão linear, detecção de anomalias (Z-score) e correlação Pearson.
    """
    def __init__(self):
        pass

    def _prepare_data_frame(self, data: List[Dict], value_col: str = 'value') -> pd.DataFrame:
        """Converte lista de dicionários para DataFrame e prepara as colunas."""
        if not data:
            return pd.DataFrame()
            
        df = pd.DataFrame(data)
        
        # Garante que a coluna de valor é numérica
        if value_col in df.columns:
            df[value_col] = pd.to_numeric(df[value_col], errors='coerce')
        
        # Converte timestamp para datetime
        if 'timestamp' in df.columns:
             # Tenta converter o timestamp para algo que o pandas reconheça
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        
        return df.dropna(subset=[value_col, 'timestamp']).sort_values(by='timestamp')

    def linear_regression_trend(self, data: List[Dict], value_col: str = 'value'):
        """Calcula a tendência de regressão linear (ex: vitals vs. tempo)."""
        df = self._prepare_data_frame(data, value_col)
        
        if df.empty or len(df) < 2:
            return None
            
        # Usa o índice numérico (pontos sequenciais) como a variável X para a regressão temporal simples
        x = np.arange(len(df))
        y = df[value_col].values

        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        
        return {
            "slope": slope, # Tendência: positivo = aumento, negativo = queda
            "r_squared": r_value**2,
            "p_value": p_value,
            "n_points": len(df)
        }

    def anomaly_detection_zscore(self, data: List[Dict], value_col: str = 'value', threshold: float = 2.5):
        """Detecta anomalias usando Z-score."""
        df = self._prepare_data_frame(data, value_col)
        
        if df.empty or len(df) < 2:
            return []
            
        series = df[value_col]
        mean = series.mean()
        std = series.std()

        if std == 0:
            return [] # Não há desvio

        df['z_score'] = (series - mean) / std
        anomalies = df[abs(df['z_score']) > threshold]
        
        # Retorna apenas os registros anômalos
        return anomalies[['timestamp', value_col, 'z_score']].to_dict('records')

    def pearson_correlation(self, data1: List[Dict], value_col1: str, data2: List[Dict], value_col2: str):
        """Calcula a correlação de Pearson entre duas séries de dados (alinhadas por tempo)."""
        df1 = self._prepare_data_frame(data1, value_col1)
        df2 = self._prepare_data_frame(data2, value_col2)
        
        # Merge baseado no timestamp para alinhar os dados
        df_merged = pd.merge(df1, df2, on='timestamp', suffixes=('_1', '_2'))
        df_merged = df_merged.dropna(subset=[f'{value_col1}_1', f'{value_col2}_2'])

        if len(df_merged) < 2:
            return None

        series1 = df_merged[f'{value_col1}_1']
        series2 = df_merged[f'{value_col2}_2']

        corr, p_value = stats.pearsonr(series1, series2)
        
        return {
            "correlation": corr, 
            "p_value": p_value,
            "n_pairs": len(df_merged)
        }

    def weekly_trend(self, data: List[Dict], value_col: str = 'value'):
        """Calcula a tendência semanal (média da última semana vs. semana anterior)."""
        df = self._prepare_data_frame(data, value_col)
        df = df.set_index('timestamp')
        
        if df.empty:
            return None
            
        # Últimos 14 dias
        last_14_days = df.last('14D') 
        
        if len(last_14_days) < 7: 
            return {"trend_change_percent": 0.0, "current_weekly_avg": last_14_days[value_col].mean()}
            
        # Semana atual (últimos 7 dias)
        week2 = last_14_days.last('7D')[value_col].mean()
        # Semana anterior (7 dias antes)
        week1 = last_14_days.first('7D')[value_col].mean() 
        
        # Mudança percentual
        if week1 is None or np.isnan(week1) or week1 == 0:
             trend_change = 0.0
        else:
            trend_change = ((week2 - week1) / week1) * 100 
        
        return {
            "trend_change_percent": trend_change,
            "current_weekly_avg": week2
        }
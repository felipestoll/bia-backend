# orchestrator.py
from datetime import datetime, timedelta
# A importação do MLEngine e do db pressupõe que eles estão na mesma pasta
from ml_engine import MLEngine 
from firebase_admin_config import db 
from pytz import timezone
from typing import List, Dict
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('Orchestrator')

ml_engine = MLEngine()
SAO_PAULO_TZ = timezone('America/Sao_Paulo') 

class Orchestrator:
    """
    Orchestrator (v0.2) para processamento de dados, análise temporal
    e geração de insights. Integra o ML Engine v0.1.
    """
    
    async def process_vitals_and_generate_insights(self, user_id: str, vital_type: str, new_data: Dict):
        """
        Gatilho principal após o registro de um novo dado vital.
        """
        logger.info(f"Iniciando orquestração para {user_id}, tipo: {vital_type}")
        
        current_value = new_data.get('value', 0.0)
        
        # 1. Análise Temporal & Regras Condicionais Simples
        self._check_simple_rules(user_id, vital_type, current_value)
            
        # 2. Coleta de dados históricos (últimos 30 dias)
        history_data = await self._fetch_history_data(user_id, vital_type, limit=30)
        
        if not history_data:
            return

        # 3. Integração com ML Engine (v0.1)
        insights_generated = []

        # Detecção de Anomalias (Z-score)
        anomaly_results = ml_engine.anomaly_detection_zscore(history_data, value_col='value', threshold=2.5)
        insights_generated.extend(self._process_anomaly_insights(user_id, vital_type, new_data, anomaly_results))
                    
        # Tendência Semanal
        weekly_trend = ml_engine.weekly_trend(history_data, value_col='value')
        insights_generated.extend(self._process_weekly_trend_insights(user_id, vital_type, weekly_trend))
        
        # Regressão Linear (tendência ao longo do tempo)
        regression_trend = ml_engine.linear_regression_trend(history_data, value_col='value')
        insights_generated.extend(self._process_regression_insights(user_id, vital_type, regression_trend))

        # 4. Geração de Insights de Correlação (Exemplo)
        # Se for um dado de sono, tenta correlacionar com HRV
        if vital_type == 'sleep':
            hrv_data = await self._fetch_history_data(user_id, 'hrv', limit=30)
            if hrv_data and len(history_data) >= 2:
                correlation = ml_engine.pearson_correlation(history_data, 'value', hrv_data, 'value')
                insights_generated.extend(self._process_correlation_insights(user_id, 'sleep_vs_hrv', correlation))


        # 5. Grava Insights
        for insight in insights_generated:
            self._save_insight(user_id, insight)

        logger.info(f"Orquestração concluída. Total de {len(insights_generated)} insights gerados.")


    def _check_simple_rules(self, user_id: str, vital_type: str, value: float):
        """Aplica regras condicionais fixas."""
        if vital_type == 'sleep' and value < 4.5:
            self.generate_critical_insight(user_id, f"Alerta Sono: Duração de apenas {value} horas. Avalie a qualidade do seu descanso.", "sleep_critical_low")
        if vital_type == 'hrv' and value < 25:
             self.generate_critical_insight(user_id, f"Alerta HRV: HRV muito baixo ({value}). Pode indicar estresse ou recuperação inadequada.", "hrv_critical_low")

    async def _fetch_history_data(self, user_id: str, vital_type: str, limit: int) -> List[Dict]:
        """Busca dados históricos de forma assíncrona."""
        history_docs = db.collection('vitals').document(user_id).collection(vital_type).order_by('timestamp', direction='DESCENDING').limit(limit).get()
        history_data = [
            {
                'timestamp': doc.to_dict().get('timestamp'), 
                'value': doc.to_dict().get('value'),
                'unit': doc.to_dict().get('unit', '')
            } for doc in history_docs
        ]
        return history_data

    def _process_anomaly_insights(self, user_id: str, vital_type: str, new_data: Dict, anomaly_results: List[Dict]) -> List[Dict]:
        """Gera insights baseados em anomalias detectadas."""
        insights = []
        new_data_ts_str = new_data.get('timestamp')
        
        for anomaly in anomaly_results:
            if str(anomaly.get('timestamp')) == str(new_data_ts_str): 
                insights.append({
                    "type": "alert",
                    "title": f"Anomalia de {vital_type.upper()} detectada",
                    "description": f"Seu valor de {vital_type} ({new_data.get('value')}) foi um outlier (Z-score: {anomaly['z_score']:.2f}).",
                    "code": f"{vital_type}_anomaly",
                    "metadata": anomaly
                })
        return insights

    def _process_weekly_trend_insights(self, user_id: str, vital_type: str, weekly_trend: Dict) -> List[Dict]:
        """Gera insights baseados em tendências semanais."""
        insights = []
        if weekly_trend and weekly_trend.get('trend_change_percent') is not None:
            change = weekly_trend['trend_change_percent']
            
            if abs(change) > 5.0: # Limiar para mudança significativa (5%)
                trend_desc = "aumentou" if change > 0 else "diminuiu"
                
                insights.append({
                    "type": "trend",
                    "title": f"Tendência Semanal de {vital_type.capitalize()}",
                    "description": f"Seu {vital_type} médio na última semana {trend_desc} em {abs(change):.1f}%.",
                    "code": f"{vital_type}_weekly_change",
                    "metadata": weekly_trend
                })
        return insights
        
    def _process_regression_insights(self, user_id: str, vital_type: str, regression_trend: Dict) -> List[Dict]:
        """Gera insights baseados em tendência de longo prazo (regressão)."""
        insights = []
        if regression_trend and abs(regression_trend.get('slope', 0)) > 0.01:
            slope = regression_trend['slope']
            trend_desc = "positiva" if slope > 0 else "negativa"
            
            insights.append({
                "type": "long_term_trend",
                "title": f"Regressão de Longo Prazo de {vital_type.capitalize()}",
                "description": f"Há uma tendência {trend_desc} clara em seu {vital_type} ao longo dos últimos {regression_trend['n_points']} registros. Slope: {slope:.2f}.",
                "code": f"{vital_type}_long_term_trend",
                "metadata": regression_trend
            })
        return insights

    def _process_correlation_insights(self, user_id: str, correlation_name: str, correlation_result: Dict) -> List[Dict]:
        """Gera insights baseados em correlações (ex: sono vs HRV)."""
        insights = []
        if correlation_result and correlation_result.get('correlation') is not None:
            corr = correlation_result['correlation']
            
            if abs(corr) > 0.6 and correlation_result['p_value'] < 0.05: # Correlação forte e significativa
                strength = "fortemente correlacionados" if corr > 0 else "fortemente inversamente correlacionados"
                insights.append({
                    "type": "correlation",
                    "title": f"Correlação Detectada: {correlation_name.replace('_', ' ').title()}",
                    "description": f"Seus dados estão {strength} (Coeficiente: {corr:.2f}).",
                    "code": f"strong_corr_{correlation_name}",
                    "metadata": correlation_result
                })
        return insights

    def generate_critical_insight(self, user_id: str, message: str, insight_code: str):
        """Grava um insight crítico de regra condicional."""
        critical_insight = {
            "type": "critical",
            "title": "ALERTA",
            "description": message,
            "code": insight_code,
            "created_at": datetime.now(SAO_PAULO_TZ).isoformat()
        }
        self._save_insight(user_id, critical_insight)

    def _save_insight(self, user_id: str, insight: Dict):
        """Salva o insight nas coleções 'insights' e 'ml_insights'."""
        insight['user_id'] = user_id
        insight['created_at'] = insight.get('created_at', datetime.now(SAO_PAULO_TZ).isoformat())
        
        db.collection('insights').document(user_id).collection('list').add(insight)
        db.collection('ml_insights').add(insight)

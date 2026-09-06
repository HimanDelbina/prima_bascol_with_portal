from rest_framework import serializers
from management.models import PartyScoringConfig, PartyScoreSnapshot


class MetricComparisonSerializer(serializers.Serializer):
    current = serializers.FloatField(allow_null=True)
    previous = serializers.FloatField(allow_null=True)
    diff = serializers.FloatField(required=False, allow_null=True)
    pct_change = serializers.FloatField(required=False, allow_null=True)
    delta_abs = serializers.FloatField(required=False, allow_null=True)
    delta_percent = serializers.FloatField(required=False, allow_null=True)
    direction = serializers.CharField(required=False)
    is_positive = serializers.BooleanField(required=False)
    is_neutral = serializers.BooleanField(required=False)


class ManagementSummarySerializer(serializers.Serializer):
    period_label = serializers.CharField()
    start_date_jalali = serializers.CharField()
    end_date_jalali = serializers.CharField()
    narrative = serializers.CharField()
    kpis = serializers.DictField()
    comparison = serializers.DictField()


class PartyScoringConfigSerializer(serializers.ModelSerializer):
    updated_by_username = serializers.CharField(source='updated_by.username', read_only=True)

    class Meta:
        model = PartyScoringConfig
        fields = [
            'id', 'enabled', 'minimum_history_days', 'minimum_tickets_for_ranking',
            'dimension_weights', 'score_thresholds', 'confidence_thresholds',
            'trend_threshold', 'calculation_version', 'updated_by_username', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by_username']

    def validate_dimension_weights(self, value):
        required_keys = [
            'weight_accuracy', 'loss_performance', 'consistency',
            'monitoring_quality', 'operational_efficiency', 'data_reliability'
        ]
        for k in required_keys:
            if k not in value:
                raise serializers.ValidationError(f"وزن بعد '{k}' الزامی است.")
            if float(value[k]) < 0:
                raise serializers.ValidationError(f"وزن بعد '{k}' نمی‌تواند منفی باشد.")
        total = sum(float(value[k]) for k in required_keys)
        if abs(total - 100.0) > 0.01:
            raise serializers.ValidationError(f"مجموع اوزان ابعاد باید دقیقاً ۱۰۰ باشد (مقدار فعلی: {total}).")
        return value


class PartyAnalyticsProfileSerializer(serializers.Serializer):
    party_id = serializers.IntegerField()
    party_name = serializers.CharField()
    party_type = serializers.CharField()
    party_type_display = serializers.CharField()
    total_tickets = serializers.IntegerField()
    completed_tickets = serializers.IntegerField()
    cancelled_tickets = serializers.IntegerField()
    total_net_weight_kg = serializers.FloatField()
    total_net_weight_ton = serializers.FloatField()
    total_final_weight_kg = serializers.FloatField()
    total_final_weight_ton = serializers.FloatField()
    average_net_weight_kg = serializers.FloatField()
    average_final_weight_kg = serializers.FloatField()
    min_net_weight_kg = serializers.FloatField()
    max_net_weight_kg = serializers.FloatField()
    first_ticket_date = serializers.CharField(allow_null=True)
    first_ticket_date_fa = serializers.CharField()
    last_ticket_date = serializers.CharField(allow_null=True)
    last_ticket_date_fa = serializers.CharField()
    active_days = serializers.IntegerField()


class PartyDiscrepancyMetricsSerializer(serializers.Serializer):
    total_discrepancy_kg = serializers.FloatField()
    average_signed_discrepancy_kg = serializers.FloatField()
    average_absolute_discrepancy_kg = serializers.FloatField()
    median_absolute_discrepancy_kg = serializers.FloatField()
    maximum_absolute_discrepancy_kg = serializers.FloatField()
    average_discrepancy_percent = serializers.FloatField()
    discrepancy_stddev = serializers.FloatField()
    tickets_with_discrepancy = serializers.IntegerField()
    discrepancy_rate = serializers.FloatField()
    tickets_with_sent_weight = serializers.IntegerField()
    missing_sent_weight_rate = serializers.FloatField()


class PartyLossMetricsSerializer(serializers.Serializer):
    total_loss_weight = serializers.FloatField()
    average_loss_weight = serializers.FloatField()
    average_loss_percent = serializers.FloatField()
    median_loss_percent = serializers.FloatField()
    maximum_loss_percent = serializers.FloatField()
    loss_stddev = serializers.FloatField()
    tickets_with_loss = serializers.IntegerField()
    loss_rate = serializers.FloatField()
    missing_loss_data_rate = serializers.FloatField()


class PartyMonitoringMetricsSerializer(serializers.Serializer):
    total_alerts = serializers.IntegerField()
    open_alerts = serializers.IntegerField()
    reviewed_alerts = serializers.IntegerField()
    resolved_alerts = serializers.IntegerField()
    ignored_alerts = serializers.IntegerField()
    low_alerts = serializers.IntegerField()
    medium_alerts = serializers.IntegerField()
    high_alerts = serializers.IntegerField()
    critical_alerts = serializers.IntegerField()
    alerts_per_100_tickets = serializers.FloatField()
    breakdown_by_type = serializers.DictField()


class PartyTurnaroundMetricsSerializer(serializers.Serializer):
    average_turnaround_minutes = serializers.FloatField()
    median_turnaround_minutes = serializers.FloatField()
    max_turnaround_minutes = serializers.FloatField()
    turnaround_stddev = serializers.FloatField()
    long_waiting_ticket_count = serializers.IntegerField()
    long_waiting_rate = serializers.FloatField()


class PartyCorrectionMetricsSerializer(serializers.Serializer):
    weight_correction_count = serializers.IntegerField()
    loss_override_count = serializers.IntegerField()
    cancel_count = serializers.IntegerField()
    tickets_with_correction = serializers.IntegerField()
    correction_rate = serializers.FloatField()


class PartyConsistencyMetricsSerializer(serializers.Serializer):
    is_sufficient_sample = serializers.BooleanField()
    weight_stddev = serializers.FloatField(allow_null=True)
    weight_variation_coef = serializers.FloatField(allow_null=True)
    loss_stddev = serializers.FloatField(allow_null=True)
    loss_variation_coef = serializers.FloatField(allow_null=True)


class PartyScoreExplanationSerializer(serializers.Serializer):
    positive_points = serializers.ListField(child=serializers.CharField())
    attention_points = serializers.ListField(child=serializers.CharField())


class PartyScoreResponseSerializer(serializers.Serializer):
    overall_score = serializers.FloatField(allow_null=True)
    raw_score = serializers.FloatField()
    level = serializers.CharField()
    level_fa = serializers.CharField()
    confidence = serializers.CharField()
    confidence_fa = serializers.CharField()
    is_score_reliable = serializers.BooleanField()
    dimension_scores = serializers.DictField()
    dimension_weights = serializers.DictField()
    calculation_version = serializers.CharField()
    explanation = PartyScoreExplanationSerializer()


class PartyDetailAnalyticsSerializer(serializers.Serializer):
    party = serializers.DictField()
    profile = PartyAnalyticsProfileSerializer()
    discrepancy_metrics = PartyDiscrepancyMetricsSerializer()
    loss_metrics = PartyLossMetricsSerializer()
    monitoring_metrics = PartyMonitoringMetricsSerializer()
    turnaround_metrics = PartyTurnaroundMetricsSerializer()
    correction_metrics = PartyCorrectionMetricsSerializer()
    consistency_metrics = PartyConsistencyMetricsSerializer()
    score = PartyScoreResponseSerializer()


class PartyRankingItemSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    percentile = serializers.FloatField()
    party_id = serializers.IntegerField()
    party_name = serializers.CharField()
    party_code = serializers.CharField(allow_null=True)
    party_type = serializers.CharField()
    party_type_fa = serializers.CharField()
    overall_score = serializers.FloatField(allow_null=True)
    score_level = serializers.CharField()
    score_level_fa = serializers.CharField()
    confidence = serializers.CharField()
    confidence_fa = serializers.CharField()
    completed_tickets = serializers.IntegerField()
    total_tonnage = serializers.FloatField()
    avg_discrepancy_kg = serializers.FloatField()
    avg_loss_percent = serializers.FloatField()
    alert_rate = serializers.FloatField()
    avg_turnaround_min = serializers.FloatField()
    weight_accuracy_score = serializers.FloatField()
    loss_performance_score = serializers.FloatField()
    consistency_score = serializers.FloatField()
    monitoring_quality_score = serializers.FloatField()
    operational_efficiency_score = serializers.FloatField()
    data_reliability_score = serializers.FloatField()
    explanation = PartyScoreExplanationSerializer()


class PartyRankingResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    minimum_tickets_applied = serializers.IntegerField()
    ordering = serializers.CharField()
    results = PartyRankingItemSerializer(many=True)


class PartyTrendResponseSerializer(serializers.Serializer):
    period = serializers.DictField()
    kpi_comparison = serializers.DictField(child=MetricComparisonSerializer())
    current_analysis = PartyDetailAnalyticsSerializer()
    previous_analysis = PartyDetailAnalyticsSerializer()


class PartyComparisonItemSerializer(serializers.Serializer):
    party_id = serializers.IntegerField()
    party_name = serializers.CharField()
    party_type = serializers.CharField()
    party_type_fa = serializers.CharField()
    score = PartyScoreResponseSerializer()
    volume = serializers.DictField()
    discrepancy = serializers.DictField()
    loss = serializers.DictField()
    monitoring = serializers.DictField()
    turnaround = serializers.DictField()


class PartyComparisonResponseSerializer(serializers.Serializer):
    parties_count = serializers.IntegerField()
    product_context = serializers.CharField()
    comparison = PartyComparisonItemSerializer(many=True)

from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('community_challenge', '0001_initial'),
        ('bd_models', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='communitychallenge',
            name='type',
            field=models.CharField(choices=[('balls_caught', 'Global Balls Caught'), ('specials_caught', 'Global Specials Caught'), ('specific_ball', 'Specific Ball Caught'), ('specific_special', 'Specific Special Caught'), ('manual', 'Manual Progress')], default='manual', max_length=20),
        ),
        migrations.AddField(
            model_name='communitychallenge',
            name='target_amount',
            field=models.PositiveIntegerField(default=100, help_text='Goal amount for the challenge'),
        ),
        migrations.AddField(
            model_name='communitychallenge',
            name='manual_progress',
            field=models.PositiveIntegerField(default=0, help_text='Current progress (only for Manual type)'),
        ),
        migrations.AddField(
            model_name='communitychallenge',
            name='ball',
            field=models.ForeignKey(blank=True, help_text="Required for 'Specific Ball Caught'", null=True, on_delete=django.db.models.deletion.SET_NULL, to='bd_models.ball'),
        ),
        migrations.AddField(
            model_name='communitychallenge',
            name='special',
            field=models.ForeignKey(blank=True, help_text="Required for 'Specific Special Caught'", null=True, on_delete=django.db.models.deletion.SET_NULL, to='bd_models.special'),
        ),
    ]

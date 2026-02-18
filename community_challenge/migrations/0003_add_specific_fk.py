from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('community_challenge', '0002_add_core_features'),
        ('bd_models', '0001_initial'),
    ]

    operations = [
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

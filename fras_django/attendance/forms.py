from django import forms
from django.utils import timezone


class StartSessionForm(forms.Form):
    subject       = forms.CharField(max_length=100)
    classroom     = forms.CharField(max_length=50)
    session_label = forms.CharField(
        max_length=100,
        required=False,
        help_text='Leave blank to auto-generate from timestamp.'
    )
    source = forms.ChoiceField(
        choices=[('rtsp', 'Live RTSP Camera'), ('video', 'Upload Video File')],
        initial='rtsp',
        widget=forms.RadioSelect,
    )
    video_file = forms.FileField(
        required=False,
        label='Video file (MP4 / AVI)',
        help_text='Required only when source = Upload Video File.',
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('source') == 'video' and not cleaned.get('video_file'):
            self.add_error('video_file', 'Please upload a video file.')
        if not cleaned.get('session_label'):
            cleaned['session_label'] = timezone.now().strftime('%Y%m%d_%H%M%S')
        return cleaned

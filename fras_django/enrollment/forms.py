from django import forms


class EnrollSingleForm(forms.Form):
    student_id = forms.CharField(max_length=20, label='Student ID')
    name       = forms.CharField(max_length=100)
    classroom  = forms.CharField(max_length=50)
    roll_no    = forms.CharField(max_length=20, required=False, label='Roll No')
    image1     = forms.ImageField(label='Photo 1 (required)')
    image2     = forms.ImageField(label='Photo 2', required=False)
    image3     = forms.ImageField(label='Photo 3', required=False)
    image4     = forms.ImageField(label='Photo 4', required=False)


class BulkEnrollForm(forms.Form):
    csv_file   = forms.FileField(label='Students CSV (student_id, name, class, roll_no)')
    photos_zip = forms.FileField(label='Photos ZIP ({student_id}_1.jpg, {student_id}_2.jpg …)')
    classroom  = forms.CharField(max_length=50, label='Classroom ID')

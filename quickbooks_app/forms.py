from django import forms


class QuickBooksCustomerForm(forms.Form):
    display_name = forms.CharField(max_length=255)
    email = forms.EmailField(required=False)
    phone = forms.CharField(required=False)

    account_name = forms.CharField(max_length=255)
    account_type = forms.CharField(max_length=100)
    account_sub_type = forms.CharField(max_length=100)
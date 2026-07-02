import json, os
import pandas as pd
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .analysis import analyze_file
from .api_client import fetch_context
from .export import generate_excel
from .forms import UploadFileForm
from .imputation import get_imputed_csv, NUMERIC_STRATEGIES, CATEGORICAL_STRATEGIES, SKLEARN_AVAILABLE
from .models import UploadedFile


def upload_file(request):
    if request.method=='POST':
        form=UploadFileForm(request.POST,request.FILES)
        if form.is_valid():
            uploaded=form.save(commit=False)
            if request.user.is_authenticated: uploaded.user=request.user
            uploaded.save()
            file_path=uploaded.file.path
            analysis=analyze_file(file_path)
            uploaded.analysis_result=analysis
            uploaded.save()
            return redirect('results',pk=uploaded.pk)
    else: form=UploadFileForm()
    return render(request,'analyzer/upload.html',{'form':form})

def results(request,pk):
    try:
        uploaded=get_object_or_404(UploadedFile,pk=pk)
        analysis=uploaded.analysis_result or {}
        if analysis.get('error'): return render(request,'analyzer/error.html',{'error':analysis['error']})
        api_data=[]
        try: api_data=fetch_context(column_names=analysis.get('columns',[]),filename=analysis.get('filename',''))
        except Exception as e: api_data=[{'error':str(e)}]
        missing_counts=analysis.get('missing_values',{})
        dtypes=analysis.get('dtypes',{}); numeric_set={c for c,t in dtypes.items() if any(k in t for k in ('int','float'))}
        recommendations={}
        if missing_counts:
            multi=sum(1 for v in missing_counts.values() if v>0)>=3
            for col,n in missing_counts.items():
                if n==0: continue
                pct=round(n/max(analysis['shape'][0],1)*100,2); is_num=col in numeric_set
                if pct>60: strat='constant'
                elif pct>30: strat='knn' if multi and SKLEARN_AVAILABLE else ('median' if is_num else 'mode')
                elif pct>5: strat='iterative' if multi and SKLEARN_AVAILABLE else ('mean' if is_num else 'mode')
                else: strat='mean' if is_num else 'mode'
                recommendations[col]={'strategy':strat,'pct':pct,'is_numeric':is_num}
        return render(request,'analyzer/results.html',{'analysis':analysis,'api_data':api_data,'plot_data_json':json.dumps(analysis.get('plot_data',{})),'recommendations':recommendations,'numeric_strategies':NUMERIC_STRATEGIES,'categorical_strategies':CATEGORICAL_STRATEGIES,'sklearn_available':SKLEARN_AVAILABLE,'uploaded_pk':pk})
    except Exception as e: return render(request,'analyzer/error.html',{'error':str(e)})

def export_excel(request,pk):
    uploaded=get_object_or_404(UploadedFile,pk=pk)
    analysis=uploaded.analysis_result or {}
    if analysis.get('error'): return HttpResponse('Analysis contains errors.',status=400)
    try:
        data=generate_excel(analysis); fname=analysis.get('filename','analysis').replace('.csv','')
        resp=HttpResponse(data,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition']=f'attachment; filename="{fname}_report.xlsx"'
        return resp
    except Exception as e: return HttpResponse(f'Export failed: {e}',status=500)

@require_POST
def impute(request,pk):
    uploaded = get_object_or_404(UploadedFile,pk=pk)
    analysis = uploaded.analysis_result or {}
    try:
        body = json.loads(request.body); strategies=body.get('strategies',{}); constants=body.get('constants',{})

        if not uploaded.file or not uploaded.file.name:
            return JsonResponse({'error':'Original file is no longer available. Please re-upload your dataset.'},status=400)
        file_path = uploaded.file.path
        if not os.path.exists(file_path):
            return JsonResponse({'error':'Original file is no longer available on the server. Please re-upload your dataset.'},status=400)

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.xlsx':
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path, keep_default_na=False, na_values=[])
        csv_bytes = get_imputed_csv(df,strategies,constants)
        fname = analysis.get('filename','data').replace('.csv','')
        resp = HttpResponse(csv_bytes,content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="{fname}_imputed.csv"'
        return resp
    except Exception as e: return JsonResponse({'error':str(e)},status=500)

@login_required
def history(request):
    uploads = UploadedFile.objects.filter(user=request.user).order_by('-uploaded_at')
    return render(request,'analyzer/history.html',{'uploads':uploads})

@login_required
@require_POST
def delete_analysis(request,pk):
    uploaded = get_object_or_404(UploadedFile,pk=pk,user=request.user)
    uploaded.delete(); messages.success(request,'Analysis deleted.')
    return redirect('history')

def register_view(request):
    form=UserCreationForm(request.POST) if request.method=='POST' else UserCreationForm()
    if request.method=='POST' and form.is_valid():
        user=form.save(); login(request,user); return redirect('upload')
    return render(request,'analyzer/auth.html',{'form':form,'mode':'register'})

def login_view(request):
    form=AuthenticationForm(data=request.POST) if request.method=='POST' else AuthenticationForm()
    if request.method=='POST' and form.is_valid():
        login(request,form.get_user()); return redirect(request.GET.get('next','upload'))
    return render(request,'analyzer/auth.html',{'form':form,'mode':'login'})

def logout_view(request):
    logout(request); return redirect('upload')
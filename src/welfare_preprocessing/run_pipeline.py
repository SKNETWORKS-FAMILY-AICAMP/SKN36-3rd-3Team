"""CLI 실행 예: python run_pipeline.py normalize --input path --output path"""
import argparse,json
from pathlib import Path
from welfare_pipeline import normalize_policies,region_candidates,region_selection,elderly_filter,quality_checks
from welfare_pipeline.collect_local_welfare import WelfareCollector,merge_list_detail,CollectionPaused
from welfare_pipeline.io_utils import read_jsonl,write_jsonl

def main():
    p=argparse.ArgumentParser(description='지자체 복지정책 파이프라인')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('normalize');a.add_argument('--input',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('region-candidates');a.add_argument('--input',required=True);a.add_argument('--csv',required=True)
    a=sub.add_parser('region-select');a.add_argument('--input',required=True);a.add_argument('--candidates',required=True);a.add_argument('--output-dir',required=True)
    a=sub.add_parser('elderly');a.add_argument('--input',required=True);a.add_argument('--output-dir',required=True)
    a=sub.add_parser('audit');a.add_argument('--input',required=True);a.add_argument('--id-field',default='policy_id')
    a=sub.add_parser('collect');a.add_argument('--region',default='전남광주통합특별시');a.add_argument('--slug',default='jeonnam');a.add_argument('--work-dir',required=True);a.add_argument('--max-calls',type=int,default=100);a.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='normalize': result=normalize_policies.run(args.input,args.output)
    elif args.command=='region-candidates':result=region_candidates.run(args.input,args.csv)
    elif args.command=='region-select':result=region_selection.run(args.input,args.candidates,args.output_dir)
    elif args.command=='elderly':result=elderly_filter.run(args.input,args.output_dir)
    elif args.command=='audit':result=quality_checks.report(args.input,args.id_field)
    else:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        c=WelfareCollector(os.environ.get('DATA_GO_KR_API_KEY'),args.work_dir,max_calls=args.max_calls)
        try: rows,stat=c.list_region(args.region,args.slug)
        except CollectionPaused as e:raise SystemExit(f'API 요청 중단: {e}')
        cache=c.collect_details(rows); merged=merge_list_detail(rows,cache)
        write_jsonl(args.output,merged)
        result={'rows':len(merged),'detail_success':sum(x['detail_fetched'] for x in merged),'calls_this_run':c.calls,'list_status':stat}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

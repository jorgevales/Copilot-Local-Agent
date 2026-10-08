"""Human-readable terminal summaries; execution contracts remain exact JSON."""
def readable(value, indent=0):
    if isinstance(value, bool): return 'Yes' if value else 'No'
    if isinstance(value, dict):
        return '\n'.join(' '*indent+key.replace('_',' ').capitalize()+': '+readable(item,indent+2)
                         for key,item in value.items() if item not in (None,[],{}))
    if isinstance(value,list):
        return '\n'.join(' '*indent+'• '+readable(item,indent+2) for item in value)
    return str(value)

def call_summary(call):
    args=call.get('arguments',{})
    lines=[call['name'].replace('.',' / ',1)]
    for key in ('purpose','url','selector','destination','operation','customer_reference'):
        if args.get(key): lines.append(key.replace('_',' ').capitalize()+': '+str(args[key]))
    for step in args.get('steps',[]):
        lines.append('• '+step.get('op','action').capitalize()+' '+readable(step.get('locator') or step.get('url') or ''))
        if step.get('effect'): lines.append('  Effect: '+step['effect'])
        if step.get('expect'): lines.append('  Check: '+readable(step['expect']))
    if args.get('documents'): lines.append('Files selected: '+str(len(args['documents'])))
    for key in ('read_paths','create_paths','modify_paths','network_destinations','permissions'):
        if args.get(key): lines.append(key.replace('_',' ').capitalize()+': '+readable(args[key]))
    return '\n'.join(lines)

def exchange_summary(kind, content):
    if isinstance(content,str): return content
    if kind=='tool_results':
        lines=[]
        for entry in content.get('results',[]):
            result=entry.get('result',{})
            lines.append((entry.get('tool') or 'Local action')+': '+str(result.get('status') or ('Completed' if entry.get('ok') else 'Failed')))
            if entry.get('error'): lines.append('  '+entry['error'].get('message','Action stopped.'))
            for key in ('url','title','row_count','count','revision','namespace_id','expires_at','status','saved','rejected_count'):
                if result.get(key) is not None: lines.append('  '+key.replace('_',' ').capitalize()+': '+str(result[key]))
            for key in ('text','summary','facts','rows','outputs'):
                if result.get(key): lines.append(readable(result[key])[:4000])
        if content.get('not_executed'): lines.append('Remaining dependent actions were not executed.')
        return '\n'.join(lines) or 'No actions executed.'
    return readable({key:content[key] for key in ('message','errors','instruction','goal','reason') if key in content}) or 'Contract and current context supplied.'

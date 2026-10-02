"""Bounded mathematical grammar, symbols and elementary assumption checks."""
import ast
import math
import sympy as S

SYMBOLS = {k: S.Symbol(k, real=True) for k in ['t','w','a','b','c','q','v','tau','T','w0','x0','x1','h0','h1','g0','g1','y0','y1']}
SYMBOLS.update({k:S.Symbol(k, integer=True) for k in ['n','k','m']})
SYMBOLS.update({k:S.Symbol(k) for k in ['s','z']})
t,w,s,z,n = [SYMBOLS[k] for k in ['t','w','s','z','n']]
OPAQUE = ['FT','LT','ZT','Conv','D','Int0','delta','u','x','h','g','y','X','H','G','Y']
FUNCS = {k:S.Function(k) for k in OPAQUE}
FUNCS.update({'exp':S.exp,'sin':S.sin,'cos':S.cos,'sqrt':S.sqrt,'abs':S.Abs,'Abs':S.Abs,'conjugate':S.conjugate,'re':S.re,'log':S.log})
ARITY = {'FT':(3,), 'LT':(3,), 'ZT':(3,), 'Conv':(3,), 'D':(2,3), 'Int0':(2,)}
for _f in FUNCS:
    ARITY.setdefault(_f,(1,))

def fn(name,*args): return FUNCS[name](*args)
def name(e): return e.func.__name__
def isfn(e,f): return name(e)==f
def txt(e): return str(e).replace('**','^')
def tree(e,level=0):
    if level>12: return '  '*level+'…'
    return '  '*level+(name(e) if e.args else str(e))+''.join('\n'+tree(a,level+1) for a in e.args)

class InputError(Exception): pass

def parse(text):
    if not isinstance(text,str) or not text.strip(): raise InputError('表达式不能为空。')
    if len(text)>1200: raise InputError('单行最多 1200 个字符。')
    text=text.replace('ω','w').replace('τ','tau').replace('π','pi').replace('−','-').replace('×','*').replace('^','**')
    try: root=ast.parse(text.strip(), mode='eval')
    except (SyntaxError,RecursionError) as ex: raise InputError('公式语法不正确，请使用显式乘号 * 和成对括号。') from ex
    if len(list(ast.walk(root)))>250: raise InputError('表达式过于复杂，请拆成多步。')
    denoms=[]
    def read(a,depth=0):
        if depth>22: raise InputError('嵌套层数超过 22。')
        r=lambda v:read(v,depth+1)
        if isinstance(a,ast.Constant) and type(a.value) in (int,float):
            if abs(a.value)>1e8 or not math.isfinite(a.value): raise InputError('数值超出 Demo 范围。')
            return S.Rational(str(a.value))
        if isinstance(a,ast.Name):
            if a.id in ('I','j'): return S.I
            if a.id=='pi': return S.pi
            if a.id not in SYMBOLS: raise InputError('不支持的变量：'+a.id+'。请查看语法说明。')
            return SYMBOLS[a.id]
        if isinstance(a,ast.UnaryOp) and isinstance(a.op,(ast.UAdd,ast.USub)):
            return r(a.operand) if isinstance(a.op,ast.UAdd) else -r(a.operand)
        if isinstance(a,ast.BinOp):
            l,b=r(a.left),r(a.right)
            if isinstance(a.op,ast.Add): return S.Add(l,b,evaluate=False)
            if isinstance(a.op,ast.Sub): return S.Add(l,-b,evaluate=False)
            if isinstance(a.op,ast.Mult): return S.Mul(l,b,evaluate=False)
            if isinstance(a.op,ast.Div):
                if b.is_zero is True or S.simplify(b)==0: raise InputError('分母不能为零。')
                denoms.append(b)
                return S.Mul(l,S.Pow(b,-1,evaluate=False),evaluate=False)
            if isinstance(a.op,ast.Pow):
                if b.is_number and abs(b)>16: raise InputError('数值指数绝对值上限为 16。')
                if b.is_negative:
                    if l.is_zero is True or S.simplify(l)==0: raise InputError('负次幂的底数不能为零。')
                    denoms.append(l)
                return S.Pow(l,b,evaluate=False)
        if isinstance(a,ast.Call) and isinstance(a.func,ast.Name) and a.func.id in FUNCS and not a.keywords:
            f=a.func.id
            if len(a.args) not in ARITY[f]: raise InputError(f+' 的参数数量不正确。')
            args=[r(v) for v in a.args]
            if f in ('FT','LT','ZT'):
                expected={'FT':(t,w),'LT':(t,s),'ZT':(n,z)}[f]
                if tuple(args[1:])!=expected: raise InputError(f+' 变量约定不匹配；应使用 '+str(expected))
            if f in ('Conv','D','Int0') and not isinstance(args[-1] if f!='D' or len(args)==2 else args[1],S.Symbol):
                raise InputError(f+' 的变量参数必须是变量名。')
            if f=='D' and len(args)==3 and args[2] not in (1,2): raise InputError('导数阶数支持 1 或 2。')
            return FUNCS[f](*args)
        raise InputError('只允许白名单数学语法；不支持属性访问、代码、下标或任意函数。')
    value=read(root.body)
    if value.has(S.zoo,S.oo,-S.oo,S.nan): raise InputError('表达式包含除零或非有限数值。')
    return value,denoms

def lineparse(line):
    if not isinstance(line,str): raise InputError('每行公式必须是文本。')
    parts=line.split(';')
    e,d=parse(parts[0])
    roc=''
    if len(parts)>2: raise InputError('每行只允许一个 ROC 条件。')
    if len(parts)==2:
        if not parts[1].strip().upper().startswith('ROC:'): raise InputError('收敛域格式为 ; ROC: abs(z)>1/2')
        roc=parts[1].strip()[4:].strip()
    return e,d,roc

def positive(a,c): return a.is_positive is True or str(a) in c.get('positive',[])
def nonzero(a,c): return a.is_zero is False or positive(a,c) or str(a) in c.get('nonzero',[])


def validate_context(context):
    """Validate caller data before it reaches symbolic routines or rule predicates."""
    if context is None: return {}
    if not isinstance(context,dict): raise InputError('context 必须是对象。')
    c=dict(context)
    if 'causal' in c and type(c['causal']) is not bool: raise InputError('causal 必须是布尔值。')
    for field in ('positive','nonzero'):
        values=c.get(field,[])
        if not isinstance(values,list) or len(values)>len(SYMBOLS) or any(not isinstance(v,str) or v not in SYMBOLS for v in values):
            raise InputError(field+' 必须是受支持变量名的列表。')
    initial=c.get('initial',{})
    if not isinstance(initial,dict): raise InputError('initial 必须是对象。')
    for key,value in initial.items():
        if key not in ('x0','x1','h0','h1','g0','g1','y0','y1') or type(value) not in (int,float):
            raise InputError('初值须为 x0/x1/h0/h1 等数值。')
        if abs(value)>1e8 or not math.isfinite(value): raise InputError('初值必须是绝对值不超过 1e8 的有限数值。')
        if key in c.get('positive',[]) and value<=0 or key in c.get('nonzero',[]) and value==0:
            raise InputError('数值初值与正值或非零假设矛盾。')
        if c.get('causal') and value!=0:
            raise InputError('因果信号在 0− 的初值应为 0；请取消因果条件或修正初值。')
    definitions=c.get('definitions',{})
    if not isinstance(definitions,dict) or len(definitions)>8: raise InputError('definitions 最多包含 8 个变换对。')
    for key,value in definitions.items():
        expression,_=parse(key)
        if name(expression) not in ('X','H','G','Y') or expression.args[0] not in (w,s,z):
            raise InputError('变换对键应为 X(w)、X(s)、X(z) 等频域函数。')
        parsed,_=parse(value)
        if any(name(node) in OPAQUE for node in S.preorder_traversal(parsed)):
            raise InputError('已知变换对必须使用具体表达式，不能引用未定义信号或变换。')
    return c

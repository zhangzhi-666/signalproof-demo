"""Executable transform rules and bounded rewrite search."""
from collections import deque
import sympy as S
from .syntax import SYMBOLS, t, w, s, z, n, fn, name, isfn, txt, positive, nonzero

def base(e,var): return e.is_Function and name(e) in ('x','h','g','y') and e.args==(var,)
def spectrum(e,var): return fn(name(e).upper(),var)
def affine(e,var):
    try:
        aa=S.diff(e,var); bb=S.simplify(e-aa*var)
        if not aa.has(var) and not bb.has(var): return aa,bb
    except Exception: pass
    return None
def split_const(e,var):
    if not e.is_Mul: return None
    a,b=e.as_independent(var,as_Add=False)
    return (a,b) if a!=1 else None

RULEDATA = [
('C01','卷积','卷积交换律','Conv(x,h)=Conv(h,x)','卷积存在','Conv(x(t),h(t),t)','Conv(h(t),x(t),t)'),
('C02','卷积','卷积结合律','(x*h)*g=x*(h*g)','相关卷积存在','Conv(Conv(x(t),h(t),t),g(t),t)','Conv(x(t),Conv(h(t),g(t),t),t)'),
('C03','卷积','卷积分配律','(x+h)*g=x*g+h*g','卷积存在','Conv(x(t)+h(t),g(t),t)','Conv(x(t),g(t),t)+Conv(h(t),g(t),t)'),
('C04','卷积','常数提取','(a x)*h=a(x*h)','a 与积分变量无关','Conv(2*x(t),h(t),t)','2*Conv(x(t),h(t),t)'),
('C05','卷积','单位冲激卷积','x*δ=x','分布意义','Conv(x(t),delta(t),t)','x(t)'),
('C06','卷积','移位冲激卷积','x*δ(t-a)=x(t-a)','实数时移；离散时为整数','Conv(x(t),delta(t-2),t)','x(t-2)'),
('C07','卷积','零信号卷积','x*0=0','卷积定义成立','Conv(x(t),0,t)','0'),
('C08','卷积','卷积求导','D(x*h)=(Dx)*h','可交换求导与卷积','D(Conv(x(t),h(t),t),t)','Conv(D(x(t),t),h(t),t)'),
('F01','傅里叶','傅里叶线性','F{a x+b h}=aX+bH','相关傅里叶变换存在','FT(2*x(t)+h(t),t,w)','2*X(w)+H(w)'),
('F02','傅里叶','时移性质','F{x(t-a)}=exp(-I*w*a) X(w)','a 为实数','FT(x(t-2),t,w)','exp(-2*I*w)*X(w)'),
('F03','傅里叶','频移性质','F{exp(I*b*t)x(t)}=X(w-b)','b 为实数','FT(exp(3*I*t)*x(t),t,w)','X(w-3)'),
('F04','傅里叶','尺度变换','F{x(a*t)}=X(w/a)/abs(a)','a 为非零实数','FT(x(-2*t),t,w)','X(-w/2)/2'),
('F05','傅里叶','共轭性质','F{conjugate(x(t))}=conjugate(X(-w))','相关变换存在','FT(conjugate(x(t)),t,w)','conjugate(X(-w))'),
('F06','傅里叶','时域求导','F{x^(k)}=(I*w)^k X(w)','分布意义或边界项消失','FT(D(x(t),t),t,w)','I*w*X(w)'),
('F07','傅里叶','乘以时间','F{t*x}=I*D(X,w)','频谱可微','FT(t*x(t),t,w)','I*D(X(w),w)'),
('F08','傅里叶','卷积定理','F{x*h}=X*H','卷积与变换存在','FT(Conv(x(t),h(t),t),t,w)','X(w)*H(w)'),
('F09','傅里叶','时域乘积','F{x*h普通乘法}=Conv(X,H,w)/(2*pi)','频域卷积存在','FT(x(t)*h(t),t,w)','Conv(X(w),H(w),w)/(2*pi)'),
('F10','傅里叶','冲激变换对','F{delta(t)}=1','分布意义','FT(delta(t),t,w)','1'),
('F11','傅里叶','因果指数变换对','F{exp(-a*t)u(t)}=1/(a+I*w)','a>0','FT(exp(-2*t)*u(t),t,w)','1/(2+I*w)'),
('F12','傅里叶','高斯变换对','F{exp(-a*t^2)}=sqrt(pi/a)*exp(-w^2/(4*a))','a>0','FT(exp(-2*t^2),t,w)','sqrt(pi/2)*exp(-w^2/8)'),
('L01','拉普拉斯','拉普拉斯线性','L{a x+b h}=aX+bH','相关收敛半平面公共部分','LT(2*x(t)+h(t),t,s)','2*X(s)+H(s)'),
('L02','拉普拉斯','一阶导数与初值','L{x\u2032}=sX-x(0-)','初值 x0；未给初值时保留未知判断','LT(D(x(t),t),t,s)','s*X(s)-x0'),
('L03','拉普拉斯','二阶导数与初值','L{x\u2033}=s^2 X-s*x0-x1','初值 x0 与 x1','LT(D(x(t),t,2),t,s)','s^2*X(s)-s*x0-x1'),
('L04','拉普拉斯','乘以时间','L{t*x}=-D(X,s)','可交换微分与积分','LT(t*x(t),t,s)','-D(X(s),s)'),
('L05','拉普拉斯','指数频移','L{exp(a*t)x}=X(s-a)','ROC 同步平移','LT(exp(-2*t)*x(t),t,s)','X(s+2)'),
('L06','拉普拉斯','因果时移','L{x(t-a)u(t-a)}=exp(-a*s)X(s)','a>0；因果信号','LT(x(t-2)*u(t-2),t,s)','exp(-2*s)*X(s)'),
('L07','拉普拉斯','因果卷积定理','L{x*h}=X(s)H(s)','x,h 为因果信号','LT(Conv(x(t),h(t),t),t,s)','X(s)*H(s)'),
('L08','拉普拉斯','零起点积分','L{Int0(x,t)}=X(s)/s','从0开始积分','LT(Int0(x(t),t),t,s)','X(s)/s'),
('L09','拉普拉斯','单位阶跃变换对','L{u(t)}=1/s','Re(s)>0','LT(u(t),t,s)','1/s; ROC: re(s)>0'),
('L10','拉普拉斯','因果指数变换对','L{exp(-a*t)u(t)}=1/(s+a)','Re(s)>-a','LT(exp(-2*t)*u(t),t,s)','1/(s+2); ROC: re(s)>-2'),
('Z01','Z变换','Z变换线性','Z{a x+b h}=aX+bH','ROC 至少包含公共收敛区','ZT(2*x(n)+h(n),n,z)','2*X(z)+H(z)'),
('Z02','Z变换','序列移位','Z{x(n-k)}=z^(-k)X(z)','k为整数；0与无穷端点需另检','ZT(x(n-2),n,z)','z^(-2)*X(z)'),
('Z03','Z变换','序列反转','Z{x(-n)}=X(1/z)','ROC 半径取倒数','ZT(x(-n),n,z)','X(1/z)'),
('Z04','Z变换','指数序列乘积','Z{a^n*x(n)}=X(z/a)','a≠0；ROC 半径乘abs(a)','ZT(2^n*x(n),n,z)','X(z/2)'),
('Z05','Z变换','乘以序号','Z{n*x(n)}=-z*D(X,z)','原ROC内成立','ZT(n*x(n),n,z)','-z*D(X(z),z)'),
('Z06','Z变换','离散卷积定理','Z{x*h}=X(z)H(z)','ROC 至少包含公共收敛区','ZT(Conv(x(n),h(n),n),n,z)','X(z)*H(z)'),
('Z07','Z变换','序列共轭','Z{conjugate(x(n))}=conjugate(X(conjugate(z)))','ROC 半径不变','ZT(conjugate(x(n)),n,z)','conjugate(X(conjugate(z)))'),
('Z08','Z变换','单位冲激变换对','Z{delta(n)}=1','全z平面含0、无穷','ZT(delta(n),n,z)','1'),
('Z09','Z变换','右边指数序列','Z{a^n*u(n)}=z/(z-a)','abs(z)>abs(a)','ZT((1/2)^n*u(n),n,z)','z/(z-1/2); ROC: abs(z)>1/2'),
('Z10','Z变换','左边指数序列','Z{-a^n*u(-n-1)}=z/(z-a)','abs(z)<abs(a)；a≠0','ZT(-(1/2)^n*u(-n-1),n,z)','z/(z-1/2); ROC: abs(z)<1/2'),
('F00','傅里叶','已知傅里叶变换对','FT(x(t),t,w)=X(w)','X 为 x 的已声明变换','FT(x(t),t,w)','X(w)'),
('L00','拉普拉斯','已知拉普拉斯变换对','LT(x(t),t,s)=X(s)','X 为 x 的已声明变换','LT(x(t),t,s)','X(s)'),
('Z00','Z变换','已知Z变换对','ZT(x(n),n,z)=X(z)','X 为 x 的已声明变换','ZT(x(n),n,z)','X(z)')]
RULES=[dict(zip(['id','category','name','formula','conditions','exampleBefore','exampleAfter'],q)) for q in RULEDATA]
RULEMAP={r['id']:r for r in RULES}

def rewrite(rid,e,c):
    """Returns (replacement, unresolved conditions, ROC). None means no match."""
    out=lambda v,needs=None,roc='':(v,needs or [],roc)
    if rid.startswith('C'):
        if rid=='C08' and isfn(e,'D') and isfn(e.args[0],'Conv'):
            a,b,v=e.args[0].args
            if e.args[1]==v and len(e.args)==2: return out(fn('Conv',fn('D',a,v),b,v),['整数序号不支持普通微分'] if v.is_integer else [])
        if not isfn(e,'Conv'): return None
        a,b,v=e.args
        if rid=='C01': return out(fn('Conv',b,a,v))
        if rid=='C02' and isfn(a,'Conv') and a.args[2]==v: return out(fn('Conv',a.args[0],fn('Conv',a.args[1],b,v),v))
        if rid=='C03':
            if a.is_Add: return out(S.Add(*[fn('Conv',q,b,v) for q in a.args]))
            if b.is_Add: return out(S.Add(*[fn('Conv',a,q,v) for q in b.args]))
        if rid=='C04':
            k=split_const(a,v)
            if k: return out(k[0]*fn('Conv',k[1],b,v))
            k=split_const(b,v)
            if k: return out(k[0]*fn('Conv',a,k[1],v))
        if rid in ('C05','C06'):
            if isfn(a,'delta'): a,b=b,a
            if isfn(b,'delta'):
                q=affine(b.args[0],v)
                if q and q[0]==1:
                    shift=-q[1]
                    if (rid=='C05' and shift==0) or (rid=='C06' and shift!=0):
                        needs=[] if not v.is_integer or shift.is_integer else ['离散时移必须是整数']
                        if not v.is_integer and shift.is_real is not True: needs.append('连续冲激的时移必须为实数')
                        if isfn(a,'Conv') and a.args[2]==v:
                            return out(fn('Conv',a.args[0].subs(v,v-shift),a.args[1],v),needs)
                        if any(name(q) in ('Conv','Int0','D') for q in S.preorder_traversal(a)): return None
                        return out(a.subs(v,v-shift),needs)
        if rid=='C07' and (a==0 or b==0): return out(S.Integer(0))
        return None
    typ={'F':'FT','L':'LT','Z':'ZT'}[rid[0]]
    if not isfn(e,typ): return None
    a,v,f=e.args; trans=lambda q:fn(typ,q,v,f)
    if rid.endswith('00') and base(a,v): return out(spectrum(a,f))
    if rid in ('F01','L01','Z01'):
        if a.is_Add: return out(S.Add(*[trans(q) for q in a.args]))
        k=split_const(a,v)
        if k: return out(k[0]*trans(k[1]))
    if rid in ('F02','F04','Z02','Z03') and a.is_Function and name(a) in ('x','h','g','y'):
        q=affine(a.args[0],v)
        if q:
            aa,bb=q; X=lambda arg:fn(name(a).upper(),arg)
            if rid=='F02' and aa==1 and bb!=0: return out(S.exp(S.I*f*bb)*X(f),[] if bb.is_real is True else ['时移参数必须为实数'])
            if rid=='F04' and aa not in (0,1):
                needs=[] if nonzero(aa,c) else [str(aa)+'≠0']
                if aa.is_real is not True or bb.is_real is not True: needs.append('尺度与时移参数必须为实数')
                return out(S.exp(S.I*f*bb/aa)*X(f/aa)/S.Abs(aa),needs)
            if rid=='Z02' and aa==1 and bb!=0: return out(f**bb*X(f),[] if bb.is_integer else ['移位为整数'])
            if rid=='Z03' and aa==-1 and bb==0: return out(X(1/f))
    if rid in ('F03','L05') and a.is_Mul:
        for ex in a.args:
            if ex.func==S.exp:
                b=S.simplify(ex.args[0]/v); rest=S.simplify(a/ex)
                if b.has(v) or not base(rest,v): continue
                if rid=='F03':
                    shift=S.simplify(b/S.I)
                    if shift.is_real is not True: continue
                    return out(spectrum(rest,f-shift))
                return out(spectrum(rest,f-b))
    if rid in ('F05','Z07') and a.func==S.conjugate and base(a.args[0],v):
        return out(S.conjugate(spectrum(a.args[0],-f if rid=='F05' else S.conjugate(f))))
    if rid in ('F06','L02','L03') and isfn(a,'D') and a.args[1]==v and base(a.args[0],v):
        order=int(a.args[2]) if len(a.args)==3 else 1
        X=spectrum(a.args[0],f); sg=name(a.args[0])
        ini=c.get('initial',{})
        x0=S.sympify(str(ini.get(sg+'0',sg+'0')),locals=SYMBOLS)
        x1=S.sympify(str(ini.get(sg+'1',sg+'1')),locals=SYMBOLS)
        if rid=='F06': return out((S.I*f)**order*X)
        if rid=='L02' and order==1: return out(f*X-x0,[] if sg+'0' in ini else ['需要提供 '+sg+'(0-) 初值'])
        if rid=='L03' and order==2: return out(f*f*X-f*x0-x1,[] if all(sg+str(k) in ini for k in (0,1)) else ['需要提供函数与一阶导数在 0- 的初值'])
    if rid in ('F07','L04','Z05') and a.is_Mul:
        rest=S.simplify(a/v)
        if base(rest,v):
            return out({'F07':S.I,'L04':-1,'Z05':-f}[rid]*fn('D',spectrum(rest,f),f))
    if rid in ('F08','L07','Z06') and isfn(a,'Conv') and a.args[2]==v:
        return out(trans(a.args[0])*trans(a.args[1]),['需要声明因果信号'] if rid=='L07' and not c.get('causal') else [])
    if rid=='F09' and a.is_Mul and len(a.args)==2 and all(base(q,v) for q in a.args):
        return out(fn('Conv',spectrum(a.args[0],f),spectrum(a.args[1],f),f)/(2*S.pi))
    if rid in ('F10','Z08') and isfn(a,'delta'):
        q=affine(a.args[0],v)
        if q and q[0]==1:
            if rid=='F10': return out(S.exp(S.I*f*q[1]),[] if q[1].is_real is True else ['连续冲激的时移必须为实数'])
            return out(f**q[1],[] if q[1].is_integer else ['离散冲激移位必须为整数'])
    if rid in ('F11','L10'):
        ex=S.simplify(a/fn('u',v)) if a.has(fn('u',v)) else (a if rid=='L10' else None)
        if ex is not None and ex.func==S.exp:
            rate=S.simplify(-ex.args[0]/v)
            if not rate.has(v):
                if rid=='F11': return out(1/(rate+S.I*f),[] if positive(rate,c) else [str(rate)+'>0'])
                return out(1/(f+rate),roc='re(s)>'+txt(-S.re(rate)))
    if rid=='F12' and a.func==S.exp:
        rate=S.simplify(-a.args[0]/v**2)
        if not rate.has(v): return out(S.sqrt(S.pi/rate)*S.exp(-f*f/(4*rate)),[] if positive(rate,c) else [str(rate)+'>0'])
    if rid=='L06' and a.is_Mul:
        for sig in a.args:
            if sig.is_Function and name(sig) in ('x','h','g','y'):
                q=affine(sig.args[0],v)
                gate=S.simplify(a/sig)
                if q and q[0]==1 and isfn(gate,'u') and S.simplify(gate.args[0]-sig.args[0])==0:
                    delay=-q[1]; needs=[]
                    if not positive(delay,c): needs.append('延迟参数>0')
                    if not c.get('causal'): needs.append('需要声明因果信号')
                    return out(S.exp(-delay*f)*spectrum(sig,f),needs)
    if rid=='L08' and isfn(a,'Int0') and a.args[1]==v: return out(trans(a.args[0])/f)
    if rid=='L09' and a in (fn('u',v),S.Integer(1)): return out(1/f,roc='re(s)>0')
    if rid=='Z04' and a.is_Mul:
        for q in a.args:
            if q.is_Pow and q.exp==v and not q.base.has(v):
                rest=S.simplify(a/q)
                if base(rest,v): return out(spectrum(rest,f/q.base),[] if nonzero(q.base,c) else ['指数底数≠0'])
    if rid in ('Z09','Z10'):
        argument=v if rid=='Z09' else -v-1
        step=next((q for q in S.preorder_traversal(a) if isfn(q,'u') and S.simplify(q.args[0]-argument)==0),None)
        rest=S.simplify(a/step) if step is not None else None
        if rest is not None:
            if rid=='Z10': rest=-rest
            if rest==1: rate=S.Integer(1)
            elif rest.is_Pow and not rest.base.has(v):
                power=S.simplify(rest.exp/v)
                if power.has(v): return None
                rate=S.simplify(rest.base**power)
            else: return None
            needs=[] if rid=='Z09' or nonzero(rate,c) else ['指数底数≠0']
            return out(f/(f-rate),needs,'abs(z)'+('>' if rid=='Z09' else '<')+txt(S.Abs(rate)))
    return None

def reduce_expression(e,c):
    """Apply only terminating, size-directed rules; leave exchanges to bounded search."""
    current=e;path=[];conditions=[];rocs=[]
    for _ in range(32):
        changed=False
        for node in S.postorder_traversal(current):
            for rule in RULES:
                if rule['id'] in ('C01','C02'): continue
                r=rewrite(rule['id'],node,c)
                if r is None: continue
                val,needs,roc=r
                new=current.xreplace({node:val})
                if new==current: continue
                path.append({'ruleId':rule['id'],'before':txt(current),'after':txt(new)})
                current=new;conditions.extend(needs)
                if roc: rocs.append(roc)
                changed=True
                break
            if changed: break
        if not changed or conditions: break
    return current,path,conditions,rocs

def candidates(e,c,maxdepth=8):
    seen={S.srepr(e)}; queue=deque([(e,[],[],[])])
    found=[]
    while queue and len(found)<90:
        current,path,conditions,rocs=queue.popleft()
        if len(path)>=maxdepth: continue
        # Specific, informative rewrites precede harmless commutativity.
        nodes=list(S.preorder_traversal(current))
        for node in nodes:
            for rule in RULES:
                if rule['id']=='C01' and len(path)>1: continue
                r=rewrite(rule['id'],node,c)
                if r is None: continue
                val,needs,roc=r
                new=current.xreplace({node:val})
                key=S.srepr(new)
                if key in seen: continue
                seen.add(key)
                step={'ruleId':rule['id'],'before':txt(current),'after':txt(new)}
                item=(new,path+[step],conditions+needs,rocs+([roc] if roc else []))
                found.append(item)
                if not needs: queue.append(item)
                if len(found)>=90: break
            if len(found)>=90: break
    return found

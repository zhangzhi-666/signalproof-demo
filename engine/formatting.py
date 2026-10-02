"""Presentation of parsed expressions; no proof or algebraic rewrites."""
import re
import sympy as S
from sympy.printing.latex import LatexPrinter
from .syntax import SYMBOLS, InputError, w, n, name, parse, lineparse

FORMAT_VERSION = 'signal-latex-1'

class SignalLatexPrinter(LatexPrinter):
    """Presentation only: print the parsed AST, never rewrite or prove it.

    A convolution operand is a function profile: x(t) becomes x, and a
    shifted input becomes x(\u00b7-a). Its evaluation variable appears once,
    outside the convolution. This also preserves nested convolutions.
    """
    def __init__(self, profile_variable=None, symbol_overrides=None, integral_depth=0):
        symbols={w:r'\omega', SYMBOLS['w0']:r'\omega_{0}'}
        for signal in ('x','h','g','y'):
            symbols[SYMBOLS[signal+'0']]=signal+r'\left(0^{-}\right)'
            symbols[SYMBOLS[signal+'1']]=signal+r"^{\prime}\left(0^{-}\right)"
        super().__init__({'symbol_names':symbols,'imaginary_unit':'j',
                          'diff_operator':'rd','fold_short_frac':False})
        self.profile_variable=profile_variable
        self.symbol_overrides=dict(symbol_overrides or {})
        self.integral_depth=integral_depth

    def _child(self, profile_variable=None, symbol_overrides=None, integral_depth=None):
        return SignalLatexPrinter(profile_variable,
            self.symbol_overrides if symbol_overrides is None else symbol_overrides,
            self.integral_depth if integral_depth is None else integral_depth)

    def _print_Symbol(self, expr, style='plain'):
        if expr in self.symbol_overrides: return self.symbol_overrides[expr]
        if expr==self.profile_variable: return r'\cdot'
        return super()._print_Symbol(expr,style)

    def _print_Mul(self, expr):
        # The safe parser preserves an explicit 1 in 1/b. Suppress that
        # typographical factor without simplifying or evaluating any operands.
        factors=[factor for factor in expr.args if factor!=S.Integer(1)]
        if len(factors)!=len(expr.args):
            if not factors: return '1'
            if len(factors)==1: return self._print(factors[0])
            expr=S.Mul(*factors,evaluate=False)
        return super()._print_Mul(expr)

    def _print_Function(self, expr, exp=None):
        nm=name(expr);args=expr.args
        if nm=='FT':
            signal,var,freq=args
            result=r'\mathcal{F}_{%s\to %s}\!\left\{%s\right\}' % (self._print(var),self._print(freq),self._print(signal))
        elif nm in ('LT','ZT'):
            signal,var,freq=args
            operator=r'\mathcal{L}_{0^{-}}' if nm=='LT' else r'\mathcal{Z}'
            result=operator+r'\!\left\{%s\right\}\!\left(%s\right)' % (self._print(signal),self._print(freq))
        elif nm=='Conv':
            left,right,var=args;profile=self._child(profile_variable=var)
            def operand(value):
                printed=profile.doprint(value)
                return r'\left(%s\right)' % printed if value.is_Add else printed
            result=r'\left[%s\ast %s\right]' % (operand(left),operand(right))
            if self.profile_variable!=var:
                brackets=(r'\left[',r'\right]') if var==n else (r'\left(',r'\right)')
                result+=brackets[0]+self._print(var)+brackets[1]
        elif nm=='D':
            signal,var=args[:2];order=args[2] if len(args)==3 else S.Integer(1)
            printed=self._print(signal);variable=self._child().doprint(var)
            power='' if order==1 else '^{'+self._print(order)+'}'
            if signal.is_Add: printed=r'\left(%s\right)' % printed
            result=r'\frac{\mathrm{d}%s %s}{\mathrm{d}%s%s}' % (power,printed,variable,power)
        elif nm=='Int0':
            signal,var=args
            depth=self.integral_depth
            dummy=r'\tau' if depth==0 and not signal.has(SYMBOLS['tau']) else r'\tau_{%d}' % (depth+1)
            overrides=dict(self.symbol_overrides);overrides[var]=dummy
            integrand=self._child(symbol_overrides=overrides,integral_depth=depth+1).doprint(signal)
            result=r'\int_{0}^{%s} %s\,\mathrm{d}%s' % (self._print(var),integrand,dummy)
        elif nm in ('x','h','g','y','X','H','G','Y','delta','u'):
            arg=args[0];label=r'\delta' if nm=='delta' else nm
            if arg==self.profile_variable: result=label
            else:
                discrete=nm in ('x','h','g','y','delta','u') and bool(arg.free_symbols.intersection({n,SYMBOLS['k'],SYMBOLS['m']}))
                brackets=(r'\left[',r'\right]') if discrete else (r'\left(',r'\right)')
                result=label+brackets[0]+self._print(arg)+brackets[1]
        else: return super()._print_Function(expr,exp)
        return r'\left(%s\right)^{%s}' % (result,exp) if exp is not None else result


def signal_latex(expr):
    return SignalLatexPrinter().doprint(expr)


def roc_latex(text):
    """Render only the supported condition grammar; no simplification/evaluation."""
    if not text: return ''
    compact=text.replace(' ','').replace('|z|','abs(z)').replace('Re(s)','re(s)').replace('Abs(z)','abs(z)')
    match=re.fullmatch(r'(abs\(z\)|re\(s\))([<>]=?)(.+)',compact)
    if not match: raise InputError('Demo 收敛域支持 abs(z)>a、abs(z)<a 或 re(s)>a。')
    bound,_=parse(match.group(3))
    variable=r'\left|z\right|' if match.group(1)=='abs(z)' else r'\operatorname{Re}\!\left(s\right)'
    operator={'<':'<','>':'>','<=':r'\le','>=':r'\ge'}[match.group(2)]
    return variable+' '+operator+' '+signal_latex(bound)


def format_steps(steps):
    if not isinstance(steps,list) or len(steps)>16: raise InputError('公式预览每次最多 16 行。')
    rows=[]
    for line in steps:
        try:
            if not isinstance(line,str): raise InputError('公式必须是文本。')
            expr,_,roc=lineparse(line)
            rows.append({'latex':signal_latex(expr),'rocLatex':roc_latex(roc),'error':''})
        except (InputError,ValueError,TypeError,RecursionError) as ex:
            rows.append({'latex':'','rocLatex':'','error':str(ex)})
    return {'formatVersion':FORMAT_VERSION,'lines':rows}


def presentation_latex(expr=None, roc=''):
    """Optional verification metadata must never decide the mathematical result."""
    try: formula=signal_latex(expr) if expr is not None else ''
    except Exception: formula=''
    try: condition=roc_latex(roc)
    except Exception: condition=''
    return formula,condition

import ply.lex as lex
import ply.yacc as yacc
import ast
from operator import eq, ge, gt, le, lt, ne
from tinydb import TinyDB, where, Query


ops = {
    "==": eq,
    "!=": ne,
    "<=": le,
    ">=": ge,
    "<": lt,
    ">": gt,
}

tokens = (
    'ID',
    'LIST',
    'SCALAR',
    'EQUAL',
    'LESS_THAN',
    'GREATER_THAN',
    'LESS_THAN_OR_EQUAL',
    'GREATER_THAN_OR_EQUAL',
    'NOT_EQUAL',
    'AND',
    'OR',
    'NOT',
    'LPAREN',
    'RPAREN',
    'IN',
)

def Lexer():



    reserved = {
        'in': 'IN'
    }

        # Define regular expressions for each token
    t_EQUAL = r'=='
    t_LESS_THAN_OR_EQUAL = r'<='
    t_GREATER_THAN_OR_EQUAL = r'>='
    t_NOT_EQUAL=r'!='
    t_LESS_THAN = r'<'
    t_GREATER_THAN = r'>'
    t_AND = r'&'
    t_OR = r'\|'
    t_NOT = r'~'
    t_LPAREN = r'\('
    t_RPAREN = r'\)'
    t_IN = r'in'
    t_ignore  = ' \t'

    # Define a rule for list literals
    def t_LIST(t):
        r'\[[^\]]*\]'
        t.type = 'LIST'  # Update the token type to 'LIST'
        t.value = ast.literal_eval(t.value)  # Evaluate the list literal to create a list object
        return t

    def t_BOOL(t):
        r'(?i)(true|false)'
        # Update the token type to 'LIST' and convert scalar value to a list object
        t.type = 'SCALAR'
        t.value = ast.literal_eval(t.value)
        return t
    def t_STRING(t):
        r'\'(.*?)\''
        # Update the token type to 'LIST' and convert scalar value to a list object
        t.type = 'SCALAR'
        t.value = ast.literal_eval(t.value)
        return t


    # Define a rule for scalar values (including integers, floats, and strings)
    def t_SCALAR(t):
        r'[0-9]+(\.[0-9]+)?|\'[^\']*\'|\"[^\"]*\"'
        # Update the token type to 'LIST' and convert scalar value to a list object
        #t.type = 'LIST'
        t.value = ast.literal_eval(t.value)
        return t


    # A regular expression rule with some action code
    def t_ID(t):
        #r'[a-zA-Z][\w._-]*'
        r'[a-zA-Z_\d]+(\.[a-zA-Z_\d]+)*'
        t.type = reserved.get(t.value, 'ID')  # Check for reserved words
        return t

    def t_error(t):
        raise SyntaxError(f'Illegal character "{t.value[0]}"')

    return lex.lex(debug=False)

#lexer = lex.lex()

def Parser():

    precedence = (
        ('left', 'OR'),
        ('left', 'AND'),
        ('left', 'NOT'),        
        ('left','EQUAL', 
                'LESS_THAN',
                'GREATER_THAN',
                'LESS_THAN_OR_EQUAL',
                'GREATER_THAN_OR_EQUAL',
                'NOT_EQUAL','IN')
    )


    def p_expression_binop(p):
        '''expr : ID EQUAL SCALAR
                  | ID NOT_EQUAL SCALAR
                  | ID LESS_THAN SCALAR
                  | ID GREATER_THAN SCALAR
                  | ID LESS_THAN_OR_EQUAL SCALAR
                  | ID GREATER_THAN_OR_EQUAL SCALAR
        '''
        p[0] = binOp(p[1],p[2],p[3])

    def p_expression_inclusion(p):
        '''expr : ID IN LIST
        '''
        p[0] = inclusionOp(p[1],p[3])

    def p_expression_group(p):
        '''expr : LPAREN expr RPAREN'''
        p[0] = (p[2])

    def p_expression_and(p):
        '''expr : expr AND expr
        '''       
        p[0] = andOp(p[1],p[3])

    def p_expression_or(p):
        '''expr : expr OR expr
        '''  
        p[0] = orOp(p[1],p[3])

    def p_expression_not(p):
        '''expr : NOT expr 
        '''  
        p[0] = notOp(p[2])

    def p_error(p): 
        raise SyntaxError(" Syntax error in input!")

    return yacc.yacc(debug=False,write_tables=0)



def binOp(k,op,v):
        opf = ops.get(op, None)
        if opf is None:
            print("Unknown operator: {0:s}".format(op))
            raise ValueError
            return where(None)
        field = _build_field_struct(k)
        return opf(field, v)

def inclusionOp(key, values):
    field = _build_field_struct(key)
    return field.one_of(values)


def andOp(left,right):
    return (left) & (right)

def orOp(left,right):
    return (left) | (right)

def notOp(expr):
    return ~expr



def _build_field_struct(key):
    field = Query()
    field = field[key]
    return field











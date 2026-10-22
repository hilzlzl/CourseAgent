"""Bounded delta debugging; every proposed reduction must remain legal and divergent.

This never guesses input grammar or supplies an expected output. It tries line
and token deletion, returning the original input when the validator rejects them.
"""
import math

def reduce_input(stdin,valid,diverges,max_attempts=16):
    original=stdin;current=stdin;attempts=0;seen={stdin}
    for tokenize,join in ((lambda s:s.splitlines(keepends=True),lambda xs:''.join(xs)),
                          (lambda s:s.split(),lambda xs:' '.join(xs)+'\n')):
        pieces=tokenize(current);parts=2
        while len(pieces)>1 and attempts<max_attempts:
            chunk=math.ceil(len(pieces)/parts);changed=False
            for offset in range(0,len(pieces),chunk):
                candidate=join(pieces[:offset]+pieces[offset+chunk:])
                if candidate in seen or len(candidate.encode())>=len(current.encode()):continue
                seen.add(candidate);attempts+=1
                try:accepted=valid(candidate) and diverges(candidate)
                except (ValueError,RuntimeError,TimeoutError):accepted=False
                if accepted:
                    current=candidate;pieces=tokenize(current);parts=max(2,parts-1);changed=True;break
                if attempts>=max_attempts:break
            if not changed:
                if parts>=len(pieces):break
                parts=min(len(pieces),parts*2)
    return {'input':current,'original_bytes':len(original.encode()),'reduced_bytes':len(current.encode()),
            'attempts':attempts,'reduced':current!=original,
            'method':'bounded_legal_input_delta_debugging','minimality_proven':False}

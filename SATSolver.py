from PropNode import *
from collections import deque

class SAT:
    def __init__(self, wff: PropNode):
        self.wff = wff
        self.constraints = []
        self.match = set()
        self.original_vars = set()
        self.sat_vars = set()
        self.pass_to_sat = set()
        self.assign = dict()
        self.pass_to_sat_var = set()

    # modify self.constraints directly
    def wff_to_CNF(self):
        # generate fresh variable name
        def generate_var(counter: int) -> (PropVariable, int):
            return PropVariable("t{}".format(counter)), counter + 1

        # work for each node
        def helper(node: PropNode, counter: int):
            if isinstance(node, PropVariable) or isinstance(node, PropConstant):
                self.original_vars.add(node)
                return node, counter

            p, counter = helper(node.left, counter)
            if node.right: q, counter = helper(node.right, counter)

            a, counter = generate_var(counter)

            if node.op == PropEnum.NOT:
                self.constraints.append([a, p])
                self.constraints.append([PropNot(p), PropNot(a)])
            elif node.op == PropEnum.AND:
                self.constraints.append([a, PropNot(p), PropNot(q)])
                self.constraints.append([p, PropNot(a)])
                self.constraints.append([q, PropNot(a)])
            elif node.op == PropEnum.OR:
                self.constraints.append([PropNot(a), p, q])
                self.constraints.append([a, PropNot(p)])
                self.constraints.append([a, PropNot(q)])
            else:
                print("-----------------------------------")

            return a, counter

        t, _ = helper(self.wff, 0)
        self.constraints.append([t])

    # update inputs to the SAT solver based on self.constraints
    def prepare_solver(self):
        for clause in self.constraints:
            for l in clause:
                if isinstance(l, PropVariable): self.sat_vars.add(l)
                else: self.sat_vars.add(PropNot(l))
        d = dict(zip(list(self.sat_vars), [i+1 for i in range(len(self.sat_vars))]))
        assert 0 not in d.values()
        for clause in self.constraints:
            c = set()
            for l in clause:
                if isinstance(l, PropVariable): c.add(d[l])
                else: c.add(-1 * d[PropNot(l)])
            self.pass_to_sat.add(frozenset(c))

        self.pass_to_sat_var = set(d.values())
        self.match = dict([(v, k) for k, v in d.items() if k in self.original_vars])

    # update assignment to the original input wff
    def assign_valid(self, assignment):
        if not assignment:
            self.assign = None
            return
        for atom, val in assignment.items():
            if atom in self.match.keys():
                self.assign[self.match[atom]] = val

class SATSolver:
    def __init__(self, delta, vars):
        self.delta = delta
        self.vars = vars
        self.learnts = set()
        self.M = dict.fromkeys(list(self.vars), None)
        self.curr_level = 0
        self.nodes = dict((k, ImplicationNode(k, None)) for k in list(self.vars))
        self.branching_vars = set()
        self.branching_hist = dict()
        self.propagate_hist = dict()
        self.branching_cnt = 0

    def solve(self):
        # update the implication graph
        def update_graph(var, clause=None):
            node = self.nodes[var]
            node.value = self.M[var]
            node.level = self.curr_level

            if clause:
                for v in [abs(literal) for literal in clause if abs(literal) != var]:
                    node.parents.append(self.nodes[v])
                    self.nodes[v].children.append(node)
                node.clause = clause

        # performing unit propagation rule
        def unit_propagate():
            def compute_value(literal):
                value = self.M[abs(literal)]
                return value if value == None else value ^ (literal < 0)

            def compute_clause(clause):
                values = list(map(compute_value, clause))
                return None if None in values else max(values)

            def is_unit_clause(clause):
                values, unassigned = [], None

                for literal in clause:
                    value = compute_value(literal)
                    values.append(value)
                    unassigned = literal if value == None else unassigned

                ret = ((values.count(False) == len(clause) - 1 and values.count(None) == 1) or
                         (len(clause) == 1 and values.count(None) == 1))
                return ret, unassigned

            while True:
                propagate_queue = deque()
                for clause in [x for x in self.delta.union(self.learnts)]:
                    clause_val = compute_clause(clause)
                    if clause_val == True:
                        continue
                    if clause_val == False:
                        return clause
                    else:
                        is_unit, unit_lit = is_unit_clause(clause)
                        if not is_unit: continue
                        prop_pair = (unit_lit, clause)
                        if prop_pair not in propagate_queue:
                            propagate_queue.append(prop_pair)
                if not propagate_queue: return None

                for prop_lit, clause in propagate_queue:
                    prop_var = abs(prop_lit)
                    self.M[prop_var] = True if prop_lit > 0 else False
                    update_graph(prop_var, clause=clause)
                    if self.curr_level in self.propagate_hist.keys(): self.propagate_hist[self.curr_level].append(prop_lit)

        # find cause of the conflict
        def conflict_analyze(conflict_clause):
            def next_recent_assigned(clause):
                for v in reversed(assign_history):
                    if v in clause or -v in clause:
                        return v, [x for x in clause if abs(x) != abs(v)]

            if self.curr_level == 0: return -1, None

            assign_history = [self.branching_hist[self.curr_level]] + list(self.propagate_hist[self.curr_level])

            pool_lits, done_lits, curr_level_lits, prev_level_lits = conflict_clause, set(), set(), set()

            while True:
                for lit in pool_lits:
                    if self.nodes[abs(lit)].level == self.curr_level: curr_level_lits.add(lit)
                    else: prev_level_lits.add(lit)

                if len(curr_level_lits) == 1: break

                last_assigned, others = next_recent_assigned(curr_level_lits)

                done_lits.add(abs(last_assigned))
                curr_level_lits = set(others)

                pool_clause = self.nodes[abs(last_assigned)].clause
                pool_lits = [l for l in pool_clause if abs(l) not in done_lits] if pool_clause is not None else []

            learnt = frozenset([l for l in curr_level_lits.union(prev_level_lits)])

            if prev_level_lits: level = max([self.nodes[abs(x)].level for x in prev_level_lits])
            else: level = self.curr_level - 1

            return level, learnt

        # backtracking to the cause and reassign
        def backtrack(level):
            for var, node in self.nodes.items():
                if node.level <= level: node.children[:] = [child for child in node.children if child.level <= level]
                else: node.value, node.level, node.parents, node.children, node.clause, self.M[node.variable] = None, -1, [], [], None, None

            self.branching_vars = set([var for var in self.vars if (self.M[var] != None and len(self.nodes[var].parents) == 0)])

            levels = list(self.propagate_hist.keys())
            for k in levels:
                if k <= level: continue
                del self.branching_hist[k]
                del self.propagate_hist[k]

        # start the loop of solving
        while not (all(var in self.M for var in self.vars) and not any(var for var in self.vars if self.M[var] == None)):
            conflict_clause = unit_propagate()
            if conflict_clause is not None:
                lvl, learnt = conflict_analyze(conflict_clause)
                if lvl < 0: return False
                self.learnts.add(learnt)
                backtrack(lvl)
                self.curr_level = lvl
            elif (all(var in self.M for var in self.vars) and not any(var for var in self.vars if self.M[var] == None)):
                break
            else:
                self.curr_level += 1
                self.branching_cnt += 1
                bt_var, bt_val = next(filter(lambda v: v in self.M and self.M[v] == None, self.vars)), True
                self.M[bt_var] = bt_val
                self.branching_vars.add(bt_var)
                self.branching_hist[self.curr_level], self.propagate_hist[self.curr_level] = bt_var, deque()
                update_graph(bt_var)
        return self.M

if __name__ == "__main__":
    a, b = PropVariable("a"), PropVariable("b")
    c = PropNot(PropAnd(a, b))
    s = SAT(c)
    s.wff_to_CNF()
    print(s.constraints)
    s.prepare_solver()
    solver = SATSolver(s.pass_to_sat, s.pass_to_sat_var)
    assignment = solver.solve()
    print(s.match)
    s.assign_valid(assignment)
    print(s.assign)

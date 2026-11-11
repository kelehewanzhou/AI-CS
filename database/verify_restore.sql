-- Stable, non-sensitive counts and a full foreign-key orphan check.
SELECT format('SELECT %L || E''\t'' || count(*) FROM %I.%I;', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
\gexec
DO $$
DECLARE fk record; broken boolean;
BEGIN
  FOR fk IN
    SELECT c.conname, c.conrelid::regclass AS child, c.confrelid::regclass AS parent,
           string_agg(format('c.%I = p.%I', a.attname, b.attname), ' AND ' ORDER BY k.ord) AS join_expr,
           string_agg(format('c.%I IS NOT NULL', a.attname), ' AND ' ORDER BY k.ord) AS present_expr
    FROM pg_constraint c
    CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY k(child_key, parent_key, ord)
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.child_key
    JOIN pg_attribute b ON b.attrelid=c.confrelid AND b.attnum=k.parent_key
    WHERE c.contype='f' AND c.connamespace='public'::regnamespace
    GROUP BY c.oid, c.conname, c.conrelid, c.confrelid
  LOOP
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s c WHERE %s AND NOT EXISTS (SELECT 1 FROM %s p WHERE %s))',
                   fk.child, fk.present_expr, fk.parent, fk.join_expr) INTO broken;
    IF broken THEN RAISE EXCEPTION 'Foreign key check failed: %', fk.conname; END IF;
  END LOOP;
END $$;

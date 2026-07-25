---
name: shadcn-radix
description: shadcn/ui component library, Radix UI primitives, theming with CSS variables, react-hook-form + zod forms, TanStack Table data tables, and cva variant composition. Use for shadcn setup, shadcn add, components.json, shadcn theming, Radix accessible components, shadcn form patterns, data tables, command palette, date picker, combobox, or drawer/sheet. References css-architecture for tokens and react-best-practices for structure.
---

# shadcn/ui + Radix Primitives Skill

Copy-paste components built on Radix UI primitives. Components live in your codebase in `components/ui/` — you own them fully.

## 1. shadcn Philosophy

- **Copy-paste, not install** — `shadcn add button` copies source into your project. Edit freely.
- Components are in `components/ui/` — they are your code, not a package.
- Primitives (Radix) handle accessibility, keyboard nav, and ARIA. shadcn adds Tailwind styling on top.
- Theme is just CSS variables in `globals.css` — swap values, not components.

## 2. CLI Workflow

```bash
# Init (run once per project)
npx shadcn@latest init
# Prompts: TypeScript, Tailwind config location, src/ or not, RSC, components.json path

# Add components
npx shadcn@latest add button
npx shadcn@latest add dialog
npx shadcn@latest add form table command

# Upgrade a component (overwrites — commit first)
npx shadcn@latest add button --overwrite
```

### `components.json`
```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "app/globals.css",
    "baseColor": "slate",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils"
  }
}
```

## 3. Theming — CSS Variables in HSL

shadcn uses HSL values without the `hsl()` wrapper so Tailwind opacity modifiers work.

```css
/* app/globals.css */
@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --primary: 222.2 47.4% 11.2%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 222.2 84% 4.9%;
    --radius: 0.5rem;
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    --primary: 210 40% 98%;
    --primary-foreground: 222.2 47.4% 11.2%;
    /* … */
  }
}
```

### Tailwind Config Integration
```ts
// tailwind.config.ts — shadcn reads these CSS vars
colors: {
  background: 'hsl(var(--background))',
  foreground: 'hsl(var(--foreground))',
  primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
  // … shadcn-generated config
  border: 'hsl(var(--border))',
  ring: 'hsl(var(--ring))',
}
```

## 4. Radix Primitives — Accessible Composition

Radix exposes headless, accessible primitives. shadcn styles them; you can also use Radix directly for custom components.

```tsx
// Custom Radix dropdown (without shadcn styling)
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'

export function ActionMenu({ items }: { items: MenuItem[] }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button aria-label="Actions">⋯</button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="z-dropdown …" sideOffset={4}>
          {items.map(item => (
            <DropdownMenu.Item key={item.id} onSelect={item.action} className="…">
              {item.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
```

### Controlled vs Uncontrolled
```tsx
// Uncontrolled — Radix manages open state internally
<Dialog.Root>
  <Dialog.Trigger>Open</Dialog.Trigger>
  <Dialog.Content>…</Dialog.Content>
</Dialog.Root>

// Controlled — you manage state (needed for programmatic open/close)
const [open, setOpen] = useState(false)
<Dialog.Root open={open} onOpenChange={setOpen}>
  <Dialog.Content>…</Dialog.Content>
</Dialog.Root>
```

## 5. Form Patterns — `react-hook-form` + `zod` + shadcn Form

```tsx
'use client'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const schema = z.object({
  email: z.string().email('Invalid email address'),
  name: z.string().min(2, 'Name must be at least 2 characters'),
})

type FormValues = z.infer<typeof schema>

export function ProfileForm() {
  const form = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: FormValues) => {
    await updateProfile(values)
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input type="email" placeholder="you@example.com" {...field} />
              </FormControl>
              <FormMessage />  {/* Auto-renders zod error */}
            </FormItem>
          )}
        />
        <Button type="submit" disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? 'Saving…' : 'Save'}
        </Button>
      </form>
    </Form>
  )
}
```

## 6. Data Table — TanStack Table + shadcn Table

```tsx
'use client'
import { useReactTable, getCoreRowModel, getSortedRowModel, getFilteredRowModel, flexRender, type ColumnDef } from '@tanstack/react-table'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface User { id: string; name: string; email: string; role: string }

const columns: ColumnDef<User>[] = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'email', header: 'Email' },
  { accessorKey: 'role', header: 'Role' },
]

export function UsersTable({ data }: { data: User[] }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map(hg => (
          <TableRow key={hg.id}>
            {hg.headers.map(header => (
              <TableHead key={header.id} onClick={header.column.getToggleSortingHandler()} className="cursor-pointer select-none">
                {flexRender(header.column.columnDef.header, header.getContext())}
              </TableHead>
            ))}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map(row => (
          <TableRow key={row.id}>
            {row.getVisibleCells().map(cell => (
              <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

## 7. Common Recipes

### Command Palette (`cmdk`)
```tsx
import { Command, CommandInput, CommandList, CommandItem, CommandGroup } from '@/components/ui/command'
import { Dialog, DialogContent } from '@/components/ui/dialog'

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="p-0 max-w-md">
        <Command>
          <CommandInput placeholder="Search…" />
          <CommandList>
            <CommandGroup heading="Pages">
              <CommandItem onSelect={() => router.push('/dashboard')}>Dashboard</CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
```

### Sheet / Drawer (mobile-friendly panel)
```tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'

<Sheet open={open} onOpenChange={setOpen}>
  <SheetContent side="right" className="w-[400px]">
    <SheetHeader><SheetTitle>Edit Profile</SheetTitle></SheetHeader>
    <ProfileForm />
  </SheetContent>
</Sheet>
```

## 8. `cva` Variant Composition

```tsx
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  // Base classes
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  }
)

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
```

## 9. Checklist

- [ ] `components.json` configured with correct paths and `rsc: true` if using App Router
- [ ] CSS variables defined in `:root` and `.dark` in `globals.css`
- [ ] Tailwind `colors` map to `hsl(var(--…))` tokens
- [ ] Forms use `react-hook-form` + `zodResolver` — no manual validation
- [ ] `<FormMessage />` used for error display — not custom error elements
- [ ] TanStack Table used for sortable/filterable data tables — not manual sort logic
- [ ] Radix controlled components (`open`, `onOpenChange`) used for programmatic control
- [ ] `cva` used for multi-variant components — not conditional classNames
- [ ] `cn()` utility used for className merging — not template literals

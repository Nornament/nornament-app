# Users — what was broken and what changed

## Three bugs, not one

**1. The Users tab crashed.** It read a list called `DB.users` that stopped
existing when the sample data was removed. It threw before drawing a row. That
was my error, and it had nothing to do with you adding a login.

**2. Your new login was real but invisible — and useless.** This is the
important one. There are two records behind every person:

| | Lives in | Holds |
|---|---|---|
| **Login** | Supabase Auth | the email and password |
| **User** | the app's own table | the role, the home location, the location rights |

Creating a login in the Supabase dashboard makes the first and not the second.
`graphic@karigar.live` could type the correct password and arrive as *nobody* —
no role, no permissions, nothing on screen. Nothing in the app told you that.

**3. The Location access Save button never saved.** It sent the right values in
the wrong envelope, and the database replied that no such function existed. The
app swallowed it. This is why nothing you did on that tab stuck either.

---

## What the Users tab does now

Everything on it is live. There is no in-memory version any more — the old
"+ Add user" only changed the screen in front of you and forgot on refresh, so
it is gone rather than sitting next to the working one looking identical.

- **+ Add user** creates the login *and* the app record in one step, and shows
  you the password once. Leave the password box blank and one is generated
  (`jasper-pearl-2665` style — readable over the phone, not guessable).
- **Logins with no user record** appear in a red banner at the top with a
  **Set them up** button. An orphan is now loud instead of silent.
- **Password** issues a new one for someone who is locked out.
- **Disable** keeps every movement, sale and edit that person recorded. Nothing
  is erased; they just stop being able to sign in.

Your `graphic@karigar.live` login is now a real user — username `graphic`,
role **Graphic / Media**, all locations. I had to pick a name and username to
prove the flow worked; change either with **Edit**.

### Two doors that no longer lock behind you

An admin who switched themselves off lost admin in the same statement and could
not switch it back on. Same for demoting yourself out of Admin from a dropdown.
Both are now refused with a message telling you to ask the other admin. The
"last active admin" guard was already there and stays.

The role dropdown on a new user starts on **— choose a role —**, not Admin.
A mis-click should not hand someone cost, melt and exports.

---

## Add a piece — rebuilt

Same fields, same function underneath. What changed:

- Grouped into **Identity / Metal & measurements / Where it is / Materials**
  instead of twelve unlabelled boxes in a row.
- **Sub category, collection, quality and size now suggest** what you have
  already used on real pieces. The kind and unit dropdowns on the materials
  lines are built from your material master, so a class you add to a material
  appears there without the file being edited.
- A **running cost total** under the materials table, with a warning chip
  counting lines that have no rate. A piece that comes out at zero is almost
  always blank rates, and that is much cheaper to catch here than at row 900.
- The materials table used to run off the right edge of the window, hiding the
  cost rate, sale rate and delete columns. It scrolls now.
- **Only the jewel code is required.** That was always true; the form now says so.

## Two smaller things found while testing

- The piece page printed `Vendor: null (null)` and `average TAT: null days` on
  anything without a vendor. Now reads "not recorded".
- **Hallmarked** was hard-coded to **Yes** on every piece. On a compliance card
  that is the kind of wrong that gets noticed by someone official. It now says
  "not recorded" unless there is a HUID or a hallmark date.

## One thing I did not change

Deleting a piece leaves its **design** behind, even when that design has no
other pieces. I removed the test one by hand. Making delete clean it up
automatically would also delete any CAD or graph files attached to that design,
which is not obviously right — say the word if you want it.

---

## Tested against the live database

Signed in as a throwaway admin, then deleted it. Every one of these ran for real:

| | |
|---|---|
| Users tab | lists all users, shows the orphan banner |
| Create user | login + app record together, password returned once |
| That new person signing in | works, arrives as Sales with the right tabs |
| Sales trying to add stock | *"You do not have permission to add stock."* |
| Sales reading the user list | empty |
| Sales calling the create-user function | *"Only an admin can manage users."* |
| Set them up (adopt an orphan) | banner clears, person becomes real |
| Location access Save | HO + KOL persisted and read back |
| Add a piece | QATEST001 created, cost ₹47,483 on 9.510 g at 18K, then deleted |
| Bad role / bad location | *"Role \"MANAGER\" is not one of ADMIN, ACCOUNTS, …"* |
| Disable yourself | refused |
| Demote yourself | refused |

Test piece, test styles and both throwaway logins are gone. You are back to
three users: you, connect, and graphic.

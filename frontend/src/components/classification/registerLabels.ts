/** The register types only the deliverables it lists. A document an administrator
 *  has given a role (company standard, contract document, contractor submittal ...)
 *  that has no register type will not get one: calling it "awaiting a type" would
 *  promise something nothing keeps (#1087). A document with NO role is unknown and
 *  stays "awaiting". */
export const NOT_IN_REGISTER_LABEL = "Not in the register";

export const NOT_IN_REGISTER_HINT =
  "The register types only the deliverables it lists. This document has a role that is not a register deliverable, so it has no register type and is not waiting for one.";

-- Author: Ignacio Rodríguez Caro
-- 006: shops that do not route defective or wrong items to their support team accept them
-- as ordinary returns (StoreProfile.returns.defective_items_to_support = false).
ALTER TABLE return_requests DROP CONSTRAINT IF EXISTS return_requests_reason_check;
ALTER TABLE return_requests ADD CONSTRAINT return_requests_reason_check
    CHECK (reason IN ('doesnt_fit', 'not_as_expected', 'changed_mind', 'defective_or_damaged',
                      'wrong_item', 'other'));

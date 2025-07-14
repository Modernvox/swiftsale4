def toggle_treeview(self):
    """Toggle the visibility of the bidders table."""
    self.tree_frame.setVisible(not self.tree_frame.isVisible())
    self.toggle_button.setText("−" if self.tree_frame.isVisible() else "+")
    self.log_info(f"Bidders table visibility: {self.tree_frame.isVisible()}")

def bind_toggle_methods(gui):
    """Bind toggle-related methods to the GUI instance."""
    gui.toggle_treeview = toggle_treeview.__get__(gui, gui.__class__)